from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from brain.agents.privacy_scrub.crypto import PrivacyCrypto, PrivacyCryptoConfig
from brain.agents.privacy_scrub.removal_seed import (
    PrivacyRemovalControlSeedRepository,
    PrivacyRemovalSeedTargetMissing,
)
from brain.agents.privacy_scrub.subjects import Role, SubjectStatus


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
async def test_removal_seed_creates_five_local_record_families() -> None:
    subject_id = uuid4()
    conn = _FakeSeedConn(subject_id=subject_id)

    result = await PrivacyRemovalControlSeedRepository(conn, _crypto()).seed_subject(
        subject_id=subject_id,
        actor="ken",
        confirmed_authorization=True,
    )

    assert result.subject_id == subject_id
    assert result.broker_target_id == "spokeo"
    assert result.public_record_target_id == "ga-courts"
    assert result.counts.total_created == 5
    assert result.counts.total_skipped == 0
    assert len(conn.inserts) == 5
    assert all("example.test" not in repr(args) for _, args in conn.inserts)


@pytest.mark.asyncio
async def test_removal_seed_skips_existing_local_records() -> None:
    subject_id = uuid4()
    conn = _FakeSeedConn(subject_id=subject_id, existing=True)

    result = await PrivacyRemovalControlSeedRepository(conn, _crypto()).seed_subject(
        subject_id=subject_id,
        actor="ken",
        confirmed_authorization=True,
    )

    assert result.counts.total_created == 0
    assert result.counts.total_skipped == 5
    assert conn.inserts == []


@pytest.mark.asyncio
async def test_removal_seed_fails_closed_without_targets() -> None:
    subject_id = uuid4()
    conn = _FakeSeedConn(subject_id=subject_id, targets=False)

    with pytest.raises(PrivacyRemovalSeedTargetMissing):
        await PrivacyRemovalControlSeedRepository(conn, _crypto()).seed_subject(
            subject_id=subject_id,
            actor="ken",
            confirmed_authorization=True,
        )


class _FakeTransaction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSeedConn:
    def __init__(
        self,
        *,
        subject_id,
        existing: bool = False,
        targets: bool = True,
    ) -> None:
        self.subject_id = subject_id
        self.existing = existing
        self.targets = targets
        self.inserts: list[tuple[str, tuple[object, ...]]] = []

    def transaction(self):
        return _FakeTransaction()

    async def fetchrow(self, query: str, *args):
        if "FROM public.alpha_privacy_subjects" in query:
            if args[0] != self.subject_id:
                return None
            return {
                "id": self.subject_id,
                "user_id": "ken",
                "display_label_digest": "hmac-sha256:" + "1" * 64,
                "role": Role.ADULT.value,
                "guardian_user_id": None,
                "jurisdiction": "US_GA",
                "status": SubjectStatus.ACTIVE.value,
                "subject_payload_hash": "sha256:" + "2" * 64,
                "subject_payload_key_version": "payload-v1",
                "created_at": datetime(2026, 6, 6, tzinfo=UTC),
                "updated_at": datetime(2026, 6, 6, tzinfo=UTC),
            }
        if "FROM public.alpha_privacy_targets_cache" in query:
            if not self.targets:
                return None
            if args and args[0] == "data_broker":
                return {
                    "id": "spokeo",
                    "category": "data_broker",
                    "jurisdiction": "US_FEDERAL",
                }
            if args and args[0] == "public_record":
                return {
                    "id": "ga-courts",
                    "category": "public_record",
                    "jurisdiction": "US_GA",
                }
            return {
                "id": "spokeo",
                "category": "data_broker",
                "jurisdiction": "US_FEDERAL",
            }
        if "SELECT id" in query and self.existing:
            return {"id": uuid4()}
        if "SELECT id" in query:
            return None
        raise AssertionError(query)

    async def execute(self, query: str, *args):
        self.inserts.append((query, args))
        return "INSERT 0 1"
