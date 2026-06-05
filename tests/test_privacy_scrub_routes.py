from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from brain.agents.privacy_scrub.config import PrivacyScrubConfigError
from brain.agents.privacy_scrub.drafts import (
    CaseDraftInboxItem,
    CreatedCaseDraft,
    PrivacyDraftCaseNotFound,
    PrivacyDraftTargetNotFound,
    RetrievedCaseDraft,
    TargetReviewPacket,
)
from brain.agents.privacy_scrub.identity import IdentityTuple, TupleType
from brain.agents.privacy_scrub.repository import CreatedSubject
from brain.agents.privacy_scrub.state import (
    StoredCaseDraft,
    StoredDraftAction,
    StoredSubject,
)
from brain.agents.privacy_scrub.subjects import Role, SubjectStatus
from brain.agents.privacy_scrub.targets import (
    Jurisdiction,
    OptOutMethod,
    Target,
    TargetCategory,
)
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
        f"/v1/privacy/subjects/{uuid4()}/case-drafts",
    ):
        classes = classify_route("POST", path)
        assert classes == ["write", "security_write"]
        assert determine_risk_tier(classes) == "T2"


def test_privacy_target_routes_are_classified() -> None:
    for path in (
        "/v1/privacy/case-drafts",
        f"/v1/privacy/case-drafts/{uuid4()}",
    ):
        classes = classify_route("GET", path)
        assert classes == ["read", "security_read"]
        assert determine_risk_tier(classes) == "T2"

    read_classes = classify_route("GET", "/v1/privacy/targets")
    assert read_classes == ["read", "security_read"]
    assert determine_risk_tier(read_classes) == "T2"

    refresh_classes = classify_route("POST", "/v1/privacy/targets/refresh")
    assert refresh_classes == ["write", "security_write"]
    assert determine_risk_tier(refresh_classes) == "T2"


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
async def test_list_privacy_targets_rejects_child_before_db_touch(monkeypatch) -> None:
    def rls_connection(request):
        raise AssertionError("child actor must fail before DB access")

    monkeypatch.setattr(privacy, "rls_connection", rls_connection)

    with pytest.raises(HTTPException) as exc:
        await privacy.list_privacy_targets(_request(role="child"), "child-user")

    assert exc.value.status_code == 403
    assert exc.value.detail == "privacy_intake_forbidden"


@pytest.mark.asyncio
async def test_list_privacy_targets_reads_cached_local_registry(monkeypatch) -> None:
    calls = SimpleNamespace(conn=None)

    async def fake_list_targets(conn):
        calls.conn = conn
        return [
            {
                "id": "spokeo",
                "name": "Spokeo",
                "category": "data_broker",
                "jurisdiction": "US_FEDERAL",
                "opt_out_method": "web_form",
                "opt_out_url": "https://example.test/optout",
                "contact_email": None,
                "supports_minors": False,
                "requires_sensitive_payload": False,
                "requires_identity_document": False,
                "avg_response_days": 5,
                "last_verified": None,
                "notes": "local registry metadata",
                "yaml_source": "brokers.yaml",
                "loaded_at": None,
            }
        ]

    monkeypatch.setattr(privacy, "rls_connection", _fake_rls_connection)
    monkeypatch.setattr(privacy, "list_targets", fake_list_targets)

    response = await privacy.list_privacy_targets(_request(), "ken")

    assert response.count == 1
    assert response.targets[0].id == "spokeo"
    assert response.targets[0].opt_out_method == "web_form"
    assert calls.conn is not None


@pytest.mark.asyncio
async def test_refresh_privacy_targets_uses_bundled_yaml_only(monkeypatch) -> None:
    target = Target(
        id="local_target",
        name="Local Target",
        category=TargetCategory.DATA_BROKER,
        jurisdiction=Jurisdiction.US_FEDERAL,
        opt_out_method=OptOutMethod.WEB_FORM,
    )
    calls = SimpleNamespace(targets=None, source_label=None)

    async def fake_refresh_targets_cache(conn, targets, source_label):
        calls.targets = targets
        calls.source_label = source_label
        return len(targets)

    monkeypatch.setattr(privacy, "rls_connection", _fake_rls_connection)
    monkeypatch.setattr(privacy, "load_all_targets", lambda: [target])
    monkeypatch.setattr(privacy, "refresh_targets_cache", fake_refresh_targets_cache)

    response = await privacy.refresh_privacy_targets(_request(), "ken")

    assert response.count == 1
    assert response.source_label == "bundled_yaml"
    assert calls.targets == [target]
    assert calls.source_label == "bundled_yaml"


@pytest.mark.asyncio
async def test_refresh_privacy_targets_fails_closed_on_bad_registry(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        privacy,
        "load_all_targets",
        lambda: (_ for _ in ()).throw(ValueError("bad yaml")),
    )

    with pytest.raises(HTTPException) as exc:
        await privacy.refresh_privacy_targets(_request(), "ken")

    assert exc.value.status_code == 500
    assert exc.value.detail == "privacy_targets_registry_invalid"


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


@pytest.mark.asyncio
async def test_create_privacy_case_draft_rejects_child_before_config_load(
    monkeypatch,
) -> None:
    def load_crypto():
        raise AssertionError("child actor must fail before crypto loads")

    monkeypatch.setattr(privacy, "load_privacy_crypto", load_crypto)

    with pytest.raises(HTTPException) as exc:
        await privacy.create_privacy_case_draft(
            _request(role="child"),
            uuid4(),
            privacy.CaseDraftCreateIn(target_ids=["spokeo"]),
            "child-user",
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == "privacy_intake_forbidden"


@pytest.mark.asyncio
async def test_create_privacy_case_draft_fails_closed_when_config_missing(
    monkeypatch,
) -> None:
    def load_crypto():
        raise PrivacyScrubConfigError("privacy_scrub_config_missing")

    def rls_connection(request):
        raise AssertionError("DB must not be touched without crypto config")

    monkeypatch.setattr(privacy, "load_privacy_crypto", load_crypto)
    monkeypatch.setattr(privacy, "rls_connection", rls_connection)

    with pytest.raises(HTTPException) as exc:
        await privacy.create_privacy_case_draft(
            _request(),
            uuid4(),
            privacy.CaseDraftCreateIn(target_ids=["spokeo"]),
            "ken",
        )

    assert exc.value.status_code == 503
    assert exc.value.detail == "privacy_scrub_config_missing"


@pytest.mark.asyncio
async def test_create_privacy_case_draft_returns_review_packet_without_plaintext(
    monkeypatch,
) -> None:
    subject_id = uuid4()
    case_id = uuid4()
    action_id = uuid4()
    calls = SimpleNamespace(user_id=None, subject_id=None, target_ids=None)

    class FakeRepo:
        def __init__(self, conn, crypto) -> None:
            pass

        async def create_case_draft(self, *, user_id, subject_id, target_ids):
            calls.user_id = user_id
            calls.subject_id = subject_id
            calls.target_ids = target_ids
            return CreatedCaseDraft(
                case_draft=StoredCaseDraft(
                    id=case_id,
                    subject_id=subject_id,
                    created_by_user_id=user_id,
                    target_count=1,
                    status="draft",
                    packet_payload_hash="sha256:" + "1" * 64,
                    payload_key_version="payload-v1",
                ),
                actions=(
                    StoredDraftAction(
                        id=action_id,
                        subject_id=subject_id,
                        target_id="spokeo",
                        case_draft_id=case_id,
                        action_type="draft",
                        approval_tier="T2",
                        status="pending",
                        draft_payload_hash="sha256:" + "2" * 64,
                        payload_key_version="payload-v1",
                    ),
                ),
                review_packets=(
                    TargetReviewPacket(
                        target_id="spokeo",
                        target_name="Spokeo",
                        category="data_broker",
                        jurisdiction="US_FEDERAL",
                        opt_out_method="web_form",
                        approval_tier="T2",
                        approval_reason=(
                            "Local draft generation has no external side effects."
                        ),
                        legal_basis=(
                            "Personal data broker opt-out or suppression request."
                        ),
                        required_identifiers=("full_name_or_name", "email_or_phone"),
                        available_identity_tuple_types=("email", "full_name"),
                        evidence_checklist=("Confirm selected subject and target.",),
                        risk_flags=(),
                    ),
                ),
            )

    monkeypatch.setattr(privacy, "load_privacy_crypto", lambda: object())
    monkeypatch.setattr(privacy, "rls_connection", _fake_rls_connection)
    monkeypatch.setattr(privacy, "PrivacyCaseDraftRepository", FakeRepo)

    response = await privacy.create_privacy_case_draft(
        _request(),
        subject_id,
        privacy.CaseDraftCreateIn(target_ids=["spokeo"]),
        "ken",
    )

    assert response.case_id == case_id
    assert response.subject_id == subject_id
    assert response.target_count == 1
    assert response.action_count == 1
    assert response.actions[0].action_id == action_id
    assert response.review_packets[0].target_id == "spokeo"
    assert response.review_packets[0].available_identity_tuple_types == [
        "email",
        "full_name",
    ]
    assert calls.user_id == "ken"
    assert calls.subject_id == subject_id
    assert calls.target_ids == ("spokeo",)
    assert "KEN@example.com" not in str(response.model_dump())


@pytest.mark.asyncio
async def test_create_privacy_case_draft_maps_missing_target(monkeypatch) -> None:
    class FakeRepo:
        def __init__(self, conn, crypto) -> None:
            pass

        async def create_case_draft(self, *, user_id, subject_id, target_ids):
            raise PrivacyDraftTargetNotFound("missing_target")

    monkeypatch.setattr(privacy, "load_privacy_crypto", lambda: object())
    monkeypatch.setattr(privacy, "rls_connection", _fake_rls_connection)
    monkeypatch.setattr(privacy, "PrivacyCaseDraftRepository", FakeRepo)

    with pytest.raises(HTTPException) as exc:
        await privacy.create_privacy_case_draft(
            _request(),
            uuid4(),
            privacy.CaseDraftCreateIn(target_ids=["missing_target"]),
            "ken",
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "privacy_target_not_found"


@pytest.mark.asyncio
async def test_list_privacy_case_drafts_returns_inbox_metadata(monkeypatch) -> None:
    subject_id = uuid4()
    case_id = uuid4()
    calls = SimpleNamespace(limit=None)

    class FakeRepo:
        def __init__(self, conn, crypto) -> None:
            pass

        async def list_case_drafts(self, *, limit=25):
            calls.limit = limit
            return (
                CaseDraftInboxItem(
                    case_draft=StoredCaseDraft(
                        id=case_id,
                        subject_id=subject_id,
                        created_by_user_id="ken",
                        target_count=2,
                        status="draft",
                        packet_payload_hash="sha256:" + "1" * 64,
                        payload_key_version="payload-v1",
                    ),
                    action_count=2,
                    approval_tiers=("T2", "T4"),
                ),
            )

    monkeypatch.setattr(privacy, "load_privacy_crypto", lambda: object())
    monkeypatch.setattr(privacy, "rls_connection", _fake_rls_connection)
    monkeypatch.setattr(privacy, "PrivacyCaseDraftRepository", FakeRepo)

    response = await privacy.list_privacy_case_drafts(
        _request(),
        10,
        "ken",
    )

    assert response.count == 1
    assert response.drafts[0].case_id == case_id
    assert response.drafts[0].subject_id == subject_id
    assert response.drafts[0].action_count == 2
    assert response.drafts[0].highest_approval_tier == "T4"
    assert calls.limit == 10


@pytest.mark.asyncio
async def test_get_privacy_case_draft_returns_review_packet(monkeypatch) -> None:
    subject_id = uuid4()
    case_id = uuid4()
    action_id = uuid4()

    class FakeRepo:
        def __init__(self, conn, crypto) -> None:
            pass

        async def get_case_draft(self, case_id_arg):
            assert case_id_arg == case_id
            return RetrievedCaseDraft(
                case_draft=StoredCaseDraft(
                    id=case_id,
                    subject_id=subject_id,
                    created_by_user_id="ken",
                    target_count=1,
                    status="draft",
                    packet_payload_hash="sha256:" + "1" * 64,
                    payload_key_version="payload-v1",
                ),
                actions=(
                    StoredDraftAction(
                        id=action_id,
                        subject_id=subject_id,
                        target_id="spokeo",
                        case_draft_id=case_id,
                        action_type="draft",
                        approval_tier="T2",
                        status="pending",
                        draft_payload_hash="sha256:" + "2" * 64,
                        payload_key_version="payload-v1",
                    ),
                ),
                review_packets=(
                    TargetReviewPacket(
                        target_id="spokeo",
                        target_name="Spokeo",
                        category="data_broker",
                        jurisdiction="US_FEDERAL",
                        opt_out_method="web_form",
                        approval_tier="T2",
                        approval_reason=(
                            "Local draft generation has no external side effects."
                        ),
                        legal_basis=(
                            "Personal data broker opt-out or suppression request."
                        ),
                        required_identifiers=("full_name_or_name",),
                        available_identity_tuple_types=("full_name",),
                        evidence_checklist=("Confirm selected subject and target.",),
                        risk_flags=(),
                    ),
                ),
            )

    monkeypatch.setattr(privacy, "load_privacy_crypto", lambda: object())
    monkeypatch.setattr(privacy, "rls_connection", _fake_rls_connection)
    monkeypatch.setattr(privacy, "PrivacyCaseDraftRepository", FakeRepo)

    response = await privacy.get_privacy_case_draft(
        _request(),
        case_id,
        "ken",
    )

    assert response.case_id == case_id
    assert response.action_count == 1
    assert response.highest_approval_tier == "T2"
    assert response.actions[0].action_id == action_id
    assert response.review_packets[0].target_name == "Spokeo"
    assert "ken@example.com" not in str(response.model_dump())


@pytest.mark.asyncio
async def test_get_privacy_case_draft_maps_missing_case(monkeypatch) -> None:
    class FakeRepo:
        def __init__(self, conn, crypto) -> None:
            pass

        async def get_case_draft(self, case_id):
            raise PrivacyDraftCaseNotFound("missing")

    monkeypatch.setattr(privacy, "load_privacy_crypto", lambda: object())
    monkeypatch.setattr(privacy, "rls_connection", _fake_rls_connection)
    monkeypatch.setattr(privacy, "PrivacyCaseDraftRepository", FakeRepo)

    with pytest.raises(HTTPException) as exc:
        await privacy.get_privacy_case_draft(
            _request(),
            uuid4(),
            "ken",
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "privacy_case_draft_not_found"


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
