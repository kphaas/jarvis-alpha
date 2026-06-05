from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from brain.agents.privacy_scrub.config import PrivacyScrubConfigError
from brain.agents.privacy_scrub.identity import IdentityTuple, TupleType
from brain.agents.privacy_scrub.repository import CreatedSubject
from brain.agents.privacy_scrub.state import StoredSubject
from brain.agents.privacy_scrub.subjects import Role, SubjectStatus
from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes import privacy


def _request(
    *,
    user_id: str = "ken",
    actor_type: str = "user",
    role: str = "user",
):
    return SimpleNamespace(
        state=SimpleNamespace(
            user_id=user_id,
            actor_type=actor_type,
            role=role,
            scopes=[],
            iss="user",
        )
    )


@asynccontextmanager
async def _fake_rls_connection(request):
    yield SimpleNamespace(request=request)


def _stored_subject(subject_id: UUID, user_id: str = "ken") -> StoredSubject:
    return StoredSubject(
        id=subject_id,
        user_id=user_id,
        display_label_digest="hmac-sha256:" + "1" * 64,
        role=Role.ADULT,
        guardian_user_id=None,
        jurisdiction="US_GA",
        status=SubjectStatus.ACTIVE,
        subject_payload_hash="sha256:" + "2" * 64,
        subject_payload_key_version="payload-v1",
    )


def test_privacy_intake_routes_are_classified_t2_security_writes() -> None:
    for path in (
        "/v1/privacy/subjects",
        f"/v1/privacy/subjects/{uuid4()}/identity-tuples",
    ):
        classes = classify_route("POST", path)
        assert classes == ["write", "security_write"]
        assert determine_risk_tier(classes) == "T2"


@pytest.mark.asyncio
async def test_create_privacy_subject_rejects_child_before_config_load(
    monkeypatch,
) -> None:
    def load_crypto():
        raise AssertionError("child actor must fail before crypto loads")

    monkeypatch.setattr(privacy, "load_privacy_crypto", load_crypto)

    with pytest.raises(HTTPException) as exc:
        await privacy.create_privacy_subject(
            _request(role="child"),
            privacy.SubjectCreateIn(
                display_label="Child",
                role=Role.ADULT,
                identity_tuples=[
                    privacy.IdentityTupleIn(
                        tuple_type=TupleType.EMAIL,
                        value="child@example.com",
                    )
                ],
            ),
            "child-user",
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "privacy_intake_forbidden"


@pytest.mark.asyncio
async def test_add_privacy_identity_tuple_rejects_service_actor_before_config_load(
    monkeypatch,
) -> None:
    def load_crypto():
        raise AssertionError("service actor must fail before crypto loads")

    monkeypatch.setattr(privacy, "load_privacy_crypto", load_crypto)

    with pytest.raises(HTTPException) as exc:
        await privacy.add_privacy_identity_tuple(
            _request(actor_type="service", role="service"),
            uuid4(),
            privacy.IdentityTupleCreateIn(
                tuple_type=TupleType.EMAIL,
                value="ken@example.com",
            ),
            "svc",
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "privacy_intake_forbidden"


@pytest.mark.asyncio
async def test_create_privacy_subject_fails_closed_when_config_missing(
    monkeypatch,
) -> None:
    def load_crypto():
        raise PrivacyScrubConfigError("privacy_scrub_config_missing")

    def rls_connection(request):
        raise AssertionError("DB must not be touched without crypto config")

    monkeypatch.setattr(privacy, "load_privacy_crypto", load_crypto)
    monkeypatch.setattr(privacy, "rls_connection", rls_connection)

    with pytest.raises(HTTPException) as exc:
        await privacy.create_privacy_subject(
            _request(),
            privacy.SubjectCreateIn(
                display_label="Ken",
                role=Role.ADULT,
                identity_tuples=[
                    privacy.IdentityTupleIn(
                        tuple_type=TupleType.EMAIL,
                        value="ken@example.com",
                    )
                ],
            ),
            "ken",
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "privacy_scrub_config_missing"


@pytest.mark.asyncio
async def test_create_privacy_subject_hands_plaintext_to_repository_only(
    monkeypatch,
) -> None:
    subject_id = uuid4()
    tuple_id = uuid4()
    calls = SimpleNamespace(intake=None, conn=None, crypto=None)

    class FakeRepo:
        def __init__(self, conn, crypto) -> None:
            calls.conn = conn
            calls.crypto = crypto

        async def create_subject(self, intake):
            calls.intake = intake
            return CreatedSubject(
                subject=_stored_subject(subject_id),
                identity_tuple_ids=(tuple_id,),
            )

    monkeypatch.setattr(privacy, "load_privacy_crypto", lambda: object())
    monkeypatch.setattr(privacy, "rls_connection", _fake_rls_connection)
    monkeypatch.setattr(privacy, "PrivacySubjectRepository", FakeRepo)

    response = await privacy.create_privacy_subject(
        _request(),
        privacy.SubjectCreateIn(
            display_label="Ken",
            role=Role.ADULT,
            payload={"notes": "private context"},
            identity_tuples=[
                privacy.IdentityTupleIn(
                    tuple_type=TupleType.EMAIL,
                    value="KEN@example.com",
                    label="Primary",
                )
            ],
        ),
        "ken",
    )

    assert response.subject_id == subject_id
    assert response.identity_tuple_count == 1
    assert response.payload_key_version == "payload-v1"
    assert calls.intake is not None
    assert calls.intake.user_id == "ken"
    assert calls.intake.identity_tuples[0].raw_value == "KEN@example.com"
    assert "KEN@example.com" not in str(response.model_dump())


@pytest.mark.asyncio
async def test_create_privacy_minor_subject_defaults_guardian_to_caller(
    monkeypatch,
) -> None:
    calls = SimpleNamespace(intake=None)

    class FakeRepo:
        def __init__(self, conn, crypto) -> None:
            pass

        async def create_subject(self, intake):
            calls.intake = intake
            return CreatedSubject(
                subject=_stored_subject(uuid4()),
                identity_tuple_ids=(uuid4(),),
            )

    monkeypatch.setattr(privacy, "load_privacy_crypto", lambda: object())
    monkeypatch.setattr(privacy, "rls_connection", _fake_rls_connection)
    monkeypatch.setattr(privacy, "PrivacySubjectRepository", FakeRepo)

    await privacy.create_privacy_subject(
        _request(),
        privacy.SubjectCreateIn(
            display_label="Minor",
            role=Role.MINOR,
            identity_tuples=[
                privacy.IdentityTupleIn(
                    tuple_type=TupleType.FULL_NAME,
                    value="Minor Person",
                )
            ],
        ),
        "ken",
    )

    assert calls.intake.guardian_user_id == "ken"
    assert calls.intake.role == Role.MINOR


@pytest.mark.asyncio
async def test_add_privacy_identity_tuple_hashes_before_insert(monkeypatch) -> None:
    subject_id = uuid4()
    tuple_id = uuid4()
    calls = SimpleNamespace(tuple_obj=None)

    class FakeCrypto:
        digest_key_version = "digest-v1"

        def identity_tuple_from_value(
            self,
            subject_id_arg: UUID,
            tuple_type: TupleType,
            raw_value: str,
            *,
            label: str | None = None,
        ) -> IdentityTuple:
            assert subject_id_arg == subject_id
            assert raw_value == "KEN@example.com"
            assert label == "Primary"
            return IdentityTuple(
                id=None,
                subject_id=subject_id_arg,
                tuple_type=tuple_type,
                digest="hmac-sha256:" + "3" * 64,
                key_version=self.digest_key_version,
                label_digest="hmac-sha256:" + "4" * 64,
            )

    async def fake_get_subject(conn, subject_id_arg: UUID):
        assert subject_id_arg == subject_id
        return _stored_subject(subject_id_arg)

    async def fake_insert_identity_tuple(conn, tuple_obj):
        calls.tuple_obj = tuple_obj
        return tuple_id

    monkeypatch.setattr(privacy, "load_privacy_crypto", FakeCrypto)
    monkeypatch.setattr(privacy, "rls_connection", _fake_rls_connection)
    monkeypatch.setattr(privacy, "get_subject", fake_get_subject)
    monkeypatch.setattr(privacy, "insert_identity_tuple", fake_insert_identity_tuple)

    response = await privacy.add_privacy_identity_tuple(
        _request(),
        subject_id,
        privacy.IdentityTupleCreateIn(
            tuple_type=TupleType.EMAIL,
            value="KEN@example.com",
            label="Primary",
        ),
        "ken",
    )

    assert response.subject_id == subject_id
    assert response.identity_tuple_id == tuple_id
    assert response.inserted is True
    assert response.key_version == "digest-v1"
    assert calls.tuple_obj.digest.startswith("hmac-sha256:")
    assert "KEN@example.com" not in str(response.model_dump())


def test_privacy_route_has_no_outbound_imports_or_plaintext_logging() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "brain" / "routes" / "privacy.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "requests",
        "httpx",
        "smtplib",
        "selenium",
        "playwright",
        "logger",
        "print(",
    )

    for token in forbidden:
        assert token not in source
