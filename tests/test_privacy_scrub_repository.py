from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from brain.agents.privacy_scrub.crypto import PrivacyCrypto, PrivacyCryptoConfig
from brain.agents.privacy_scrub.identity import TupleType
from brain.agents.privacy_scrub.repository import (
    IdentityTupleInput,
    PrivacySubjectRepository,
    SubjectIntake,
)
from brain.agents.privacy_scrub.subjects import Role, SubjectStatus


class FakePrivacyConnection:
    def __init__(self) -> None:
        self.subject_id = uuid4()
        self.tuple_ids = [uuid4(), uuid4(), uuid4()]
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []
        self._tuple_index = 0
        self.subject_insert_args: tuple[object, ...] | None = None
        self.identity_insert_args: list[tuple[object, ...]] = []
        self.transaction_entries = 0
        self.transaction_exits = 0

    def transaction(self) -> "FakePrivacyConnection":
        return self

    async def __aenter__(self) -> "FakePrivacyConnection":
        self.transaction_entries += 1
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.transaction_exits += 1

    async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
        self.fetchrow_calls.append((query, args))
        if "INSERT INTO public.alpha_privacy_subjects" in query:
            self.subject_insert_args = args
            return {"id": self.subject_id}
        if "INSERT INTO public.alpha_privacy_identity_tuples" in query:
            self.identity_insert_args.append(args)
            tuple_id = self.tuple_ids[self._tuple_index]
            self._tuple_index += 1
            return {"id": tuple_id}
        if "FROM public.alpha_privacy_subjects" in query:
            return {
                "id": self.subject_id,
                "user_id": "ken",
                "display_label_digest": args[0]
                if isinstance(args[0], str)
                else "hmac-sha256:" + "1" * 64,
                "role": "adult",
                "guardian_user_id": None,
                "jurisdiction": "US_GA",
                "status": "active",
                "subject_payload_hash": "sha256:" + "2" * 64,
                "subject_payload_key_version": "payload-v1",
                "created_at": None,
                "updated_at": None,
            }
        raise AssertionError(f"unexpected fetchrow query: {query}")


def _crypto() -> PrivacyCrypto:
    return PrivacyCrypto(
        PrivacyCryptoConfig(
            digest_key="test-digest-key",
            digest_key_version="digest-v1",
            payload_key="test-payload-key",
            payload_key_version="payload-v1",
        )
    )


@pytest.mark.asyncio
async def test_repository_creates_adult_subject_with_encrypted_payload():
    conn = FakePrivacyConnection()
    repo = PrivacySubjectRepository(conn, _crypto())  # type: ignore[arg-type]

    result = await repo.create_subject(
        SubjectIntake(
            user_id="ken",
            display_label="Ken",
            role=Role.ADULT,
            payload={"email": "ken@example.com", "notes": "private"},
            identity_tuples=(
                IdentityTupleInput(TupleType.EMAIL, "KEN@example.com", "Primary"),
            ),
        )
    )

    assert result.subject.id == conn.subject_id
    assert result.subject.status == SubjectStatus.ACTIVE
    assert result.identity_tuple_ids == (conn.tuple_ids[0],)
    assert conn.transaction_entries == 1
    assert conn.transaction_exits == 1
    assert conn.subject_insert_args is not None

    (
        user_id,
        display_label_digest,
        role,
        guardian_user_id,
        jurisdiction,
        ciphertext,
        payload_hash,
        key_version,
    ) = conn.subject_insert_args

    assert user_id == "ken"
    assert str(display_label_digest).startswith("hmac-sha256:")
    assert "Ken" not in str(display_label_digest)
    assert role == "adult"
    assert guardian_user_id is None
    assert jurisdiction == "US_GA"
    assert isinstance(ciphertext, bytes)
    assert b"ken@example.com" not in ciphertext
    assert str(payload_hash).startswith("sha256:")
    assert key_version == "payload-v1"

    assert len(conn.identity_insert_args) == 1
    identity_args = conn.identity_insert_args[0]
    assert identity_args[0] == conn.subject_id
    assert identity_args[1] == "email"
    assert str(identity_args[2]).startswith("hmac-sha256:")
    assert identity_args[3] == "digest-v1"
    assert str(identity_args[4]).startswith("hmac-sha256:")


@pytest.mark.asyncio
async def test_repository_creates_minor_subject_with_guardian():
    conn = FakePrivacyConnection()
    repo = PrivacySubjectRepository(conn, _crypto())  # type: ignore[arg-type]

    await repo.create_subject(
        SubjectIntake(
            user_id="ken",
            display_label="Minor",
            role=Role.MINOR,
            guardian_user_id="ken",
            payload={"notes": "guardian approved"},
            identity_tuples=(IdentityTupleInput(TupleType.FULL_NAME, "Minor Person"),),
        )
    )

    assert conn.subject_insert_args is not None
    assert conn.subject_insert_args[2] == "minor"
    assert conn.subject_insert_args[3] == "ken"


def test_repository_rejects_minor_without_guardian_before_db_call():
    with pytest.raises(ValueError, match="guardian_user_id"):
        SubjectIntake(
            user_id="ken",
            display_label="Minor",
            role=Role.MINOR,
            payload={},
            identity_tuples=(IdentityTupleInput(TupleType.FULL_NAME, "Minor"),),
        )


def test_subject_intake_requires_identity_tuple():
    with pytest.raises(ValueError, match="identity tuple"):
        SubjectIntake(
            user_id="ken",
            display_label="Ken",
            role=Role.ADULT,
            payload={},
            identity_tuples=(),
        )


def test_repository_module_has_no_outbound_or_rls_bypass_imports():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "brain"
        / "agents"
        / "privacy_scrub"
        / "repository.py"
    )
    source = module_path.read_text(encoding="utf-8")
    forbidden = (
        "requests",
        "httpx",
        "smtplib",
        "selenium",
        "playwright",
        "set_config('rls.role', 'platform_admin'",
    )

    for token in forbidden:
        assert token not in source


def test_fake_connection_subject_id_type_guard():
    assert isinstance(FakePrivacyConnection().subject_id, UUID)
