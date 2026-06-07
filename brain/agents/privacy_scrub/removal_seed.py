"""Guarded local seed writer for P4 removal-control records.

This module writes encrypted, hash-only control-plane metadata for an existing
privacy subject. It does not contact brokers, search providers, public-record
sites, or any external network target.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg

from brain.agents.privacy_scrub.crypto import PrivacyCrypto
from brain.agents.privacy_scrub.state import StoredSubject, get_subject
from jarvis_common.logging_config import get_logger

logger = get_logger("privacy_scrub.removal_seed")


class PrivacyRemovalSeedError(ValueError):
    """Base error for P4 seed operations."""


class PrivacyRemovalSeedSubjectNotFound(PrivacyRemovalSeedError):
    """Raised when the selected subject is not readable through RLS."""


class PrivacyRemovalSeedTargetMissing(PrivacyRemovalSeedError):
    """Raised when the local target cache has no usable target."""


@dataclass(frozen=True, slots=True)
class RemovalControlSeedCounts:
    authorizations_created: int
    authorizations_skipped: int
    evidence_created: int
    evidence_skipped: int
    monitor_runs_created: int
    monitor_runs_skipped: int
    search_deindex_created: int
    search_deindex_skipped: int
    public_record_triage_created: int
    public_record_triage_skipped: int

    @property
    def total_created(self) -> int:
        return (
            self.authorizations_created
            + self.evidence_created
            + self.monitor_runs_created
            + self.search_deindex_created
            + self.public_record_triage_created
        )

    @property
    def total_skipped(self) -> int:
        return (
            self.authorizations_skipped
            + self.evidence_skipped
            + self.monitor_runs_skipped
            + self.search_deindex_skipped
            + self.public_record_triage_skipped
        )


@dataclass(frozen=True, slots=True)
class RemovalControlSeedResult:
    subject_id: UUID
    broker_target_id: str
    public_record_target_id: str | None
    payload_key_version: str
    generated_at: datetime
    counts: RemovalControlSeedCounts


class PrivacyRemovalControlSeedRepository:
    """Write P4 operational seed rows through an RLS-bound connection."""

    def __init__(self, conn: asyncpg.Connection, crypto: PrivacyCrypto) -> None:
        self._conn = conn
        self._crypto = crypto

    async def seed_subject(
        self,
        *,
        subject_id: UUID,
        actor: str,
        confirmed_authorization: bool,
    ) -> RemovalControlSeedResult:
        if not actor.strip():
            raise PrivacyRemovalSeedError("actor is required")
        if not confirmed_authorization:
            raise PrivacyRemovalSeedError("authorization confirmation is required")

        now = datetime.now(UTC)
        async with self._conn.transaction():
            subject = await get_subject(self._conn, subject_id)
            if subject is None:
                raise PrivacyRemovalSeedSubjectNotFound("privacy subject not found")

            broker_target = await self._target_for_category("data_broker")
            if broker_target is None:
                broker_target = await self._fallback_target()
            if broker_target is None:
                raise PrivacyRemovalSeedTargetMissing("privacy target cache is empty")

            public_target = await self._target_for_category("public_record")
            broker_target_id = str(broker_target["id"])
            public_target_id = (
                str(public_target["id"]) if public_target is not None else None
            )

            authorization_created = await self._ensure_authorization(
                subject=subject,
                actor=actor,
                now=now,
            )
            evidence_created = await self._ensure_evidence(
                subject=subject,
                target_id=broker_target_id,
                actor=actor,
                now=now,
            )
            monitor_created = await self._ensure_monitor_run(
                subject=subject,
                actor=actor,
                now=now,
            )
            search_created = await self._ensure_search_deindex_item(
                subject=subject,
                target_id=broker_target_id,
                now=now,
            )
            public_record_created = await self._ensure_public_record_triage(
                subject=subject,
                target_id=public_target_id,
                jurisdiction=_target_jurisdiction(public_target, subject),
                actor=actor,
                now=now,
            )

        counts = RemovalControlSeedCounts(
            authorizations_created=int(authorization_created),
            authorizations_skipped=int(not authorization_created),
            evidence_created=int(evidence_created),
            evidence_skipped=int(not evidence_created),
            monitor_runs_created=int(monitor_created),
            monitor_runs_skipped=int(not monitor_created),
            search_deindex_created=int(search_created),
            search_deindex_skipped=int(not search_created),
            public_record_triage_created=int(public_record_created),
            public_record_triage_skipped=int(not public_record_created),
        )
        logger.info(
            "privacy_removal_seed subject_id=%s created=%d skipped=%d",
            subject_id,
            counts.total_created,
            counts.total_skipped,
        )
        return RemovalControlSeedResult(
            subject_id=subject_id,
            broker_target_id=broker_target_id,
            public_record_target_id=public_target_id,
            payload_key_version=self._crypto.payload_key_version,
            generated_at=now,
            counts=counts,
        )

    async def _target_for_category(
        self,
        category: str,
    ) -> dict[str, object] | None:
        row = await self._conn.fetchrow(
            """
            SELECT id, category, jurisdiction
            FROM public.alpha_privacy_targets_cache
            WHERE category = $1
            ORDER BY name, id
            LIMIT 1
            """,
            category,
        )
        return dict(row) if row else None

    async def _fallback_target(self) -> dict[str, object] | None:
        row = await self._conn.fetchrow(
            """
            SELECT id, category, jurisdiction
            FROM public.alpha_privacy_targets_cache
            ORDER BY name, id
            LIMIT 1
            """
        )
        return dict(row) if row else None

    async def _ensure_authorization(
        self,
        *,
        subject: StoredSubject,
        actor: str,
        now: datetime,
    ) -> bool:
        existing = await self._conn.fetchrow(
            """
            SELECT id
            FROM public.alpha_privacy_authorizations
            WHERE subject_id = $1
              AND authorization_type = 'agent_authorization'
              AND status = 'active'
            LIMIT 1
            """,
            subject.id,
        )
        if existing:
            return False

        encrypted = self._crypto.encrypt_json_payload(
            {
                "record_kind": "operator_authorization_attestation",
                "subject_id": str(subject.id),
                "subject_jurisdiction": subject.jurisdiction,
                "actor": actor,
                "confirmed_authorization": True,
                "outbound_enabled": False,
                "captured_at": now.isoformat(),
            }
        )
        await self._conn.execute(
            """
            INSERT INTO public.alpha_privacy_authorizations (
                subject_id,
                authorization_type,
                status,
                created_by_user_id,
                authorization_payload_ciphertext,
                authorization_payload_hash,
                payload_key_version,
                expires_at
            )
            VALUES ($1, 'agent_authorization', 'active', $2, $3, $4, $5, $6)
            """,
            subject.id,
            actor,
            encrypted.ciphertext,
            encrypted.payload_hash,
            encrypted.key_version,
            now + timedelta(days=365),
        )
        return True

    async def _ensure_evidence(
        self,
        *,
        subject: StoredSubject,
        target_id: str,
        actor: str,
        now: datetime,
    ) -> bool:
        existing = await self._conn.fetchrow(
            """
            SELECT id
            FROM public.alpha_privacy_evidence_items
            WHERE subject_id = $1
              AND target_id = $2
              AND evidence_type = 'source_snapshot'
            LIMIT 1
            """,
            subject.id,
            target_id,
        )
        if existing:
            return False

        encrypted = self._crypto.encrypt_json_payload(
            {
                "record_kind": "operator_seed_source_snapshot",
                "subject_id": str(subject.id),
                "target_id": target_id,
                "proof_state": "local_placeholder_needs_before_after_proof",
                "captured_at": now.isoformat(),
            }
        )
        await self._conn.execute(
            """
            INSERT INTO public.alpha_privacy_evidence_items (
                subject_id,
                target_id,
                evidence_type,
                status,
                evidence_payload_ciphertext,
                evidence_payload_hash,
                payload_key_version,
                captured_by_user_id
            )
            VALUES ($1, $2, 'source_snapshot', 'captured', $3, $4, $5, $6)
            """,
            subject.id,
            target_id,
            encrypted.ciphertext,
            encrypted.payload_hash,
            encrypted.key_version,
            actor,
        )
        return True

    async def _ensure_monitor_run(
        self,
        *,
        subject: StoredSubject,
        actor: str,
        now: datetime,
    ) -> bool:
        existing = await self._conn.fetchrow(
            """
            SELECT id
            FROM public.alpha_privacy_monitor_runs
            WHERE subject_id = $1
              AND run_type = 'recurring_broker'
              AND status = 'scheduled'
            LIMIT 1
            """,
            subject.id,
        )
        if existing:
            return False

        await self._conn.execute(
            """
            INSERT INTO public.alpha_privacy_monitor_runs (
                subject_id,
                run_type,
                status,
                scheduled_for,
                coverage_count,
                created_by_user_id
            )
            VALUES ($1, 'recurring_broker', 'scheduled', $2, 1, $3)
            """,
            subject.id,
            now,
            actor,
        )
        return True

    async def _ensure_search_deindex_item(
        self,
        *,
        subject: StoredSubject,
        target_id: str,
        now: datetime,
    ) -> bool:
        result_digest = self._crypto.digest_value(
            "search_result_url",
            f"{subject.id}:{target_id}:operator-seed",
        )
        existing = await self._conn.fetchrow(
            """
            SELECT id
            FROM public.alpha_privacy_search_deindex_items
            WHERE subject_id = $1
              AND result_url_digest = $2
            LIMIT 1
            """,
            subject.id,
            result_digest,
        )
        if existing:
            return False

        encrypted = self._crypto.encrypt_json_payload(
            {
                "record_kind": "operator_seed_search_candidate",
                "subject_id": str(subject.id),
                "target_id": target_id,
                "search_provider": "google",
                "result_url_digest": result_digest,
                "captured_at": now.isoformat(),
            }
        )
        await self._conn.execute(
            """
            INSERT INTO public.alpha_privacy_search_deindex_items (
                subject_id,
                target_id,
                search_provider,
                result_url_digest,
                legal_basis,
                status,
                item_payload_ciphertext,
                item_payload_hash,
                payload_key_version,
                last_checked_at
            )
            VALUES (
                $1,
                $2,
                'google',
                $3,
                'privacy_or_outdated_content',
                'needs_review',
                $4,
                $5,
                $6,
                $7
            )
            """,
            subject.id,
            target_id,
            result_digest,
            encrypted.ciphertext,
            encrypted.payload_hash,
            encrypted.key_version,
            now,
        )
        return True

    async def _ensure_public_record_triage(
        self,
        *,
        subject: StoredSubject,
        target_id: str | None,
        jurisdiction: str,
        actor: str,
        now: datetime,
    ) -> bool:
        existing = await self._conn.fetchrow(
            """
            SELECT id
            FROM public.alpha_privacy_public_record_triage
            WHERE subject_id = $1
              AND COALESCE(target_id, '') = COALESCE($2, '')
              AND record_kind = 'court_record'
            LIMIT 1
            """,
            subject.id,
            target_id,
        )
        if existing:
            return False

        encrypted = self._crypto.encrypt_json_payload(
            {
                "record_kind": "operator_seed_public_record_triage",
                "subject_id": str(subject.id),
                "target_id": target_id,
                "jurisdiction": jurisdiction,
                "legal_process_required": True,
                "outbound_enabled": False,
                "captured_at": now.isoformat(),
            }
        )
        await self._conn.execute(
            """
            INSERT INTO public.alpha_privacy_public_record_triage (
                subject_id,
                target_id,
                jurisdiction,
                record_kind,
                triage_status,
                legal_process_required,
                triage_payload_ciphertext,
                triage_payload_hash,
                payload_key_version,
                created_by_user_id
            )
            VALUES (
                $1,
                $2,
                $3,
                'court_record',
                'legal_review_required',
                TRUE,
                $4,
                $5,
                $6,
                $7
            )
            """,
            subject.id,
            target_id,
            jurisdiction,
            encrypted.ciphertext,
            encrypted.payload_hash,
            encrypted.key_version,
            actor,
        )
        return True


def _target_jurisdiction(
    target: dict[str, object] | None,
    subject: StoredSubject,
) -> str:
    if target is None:
        return subject.jurisdiction
    jurisdiction = target.get("jurisdiction")
    return str(jurisdiction) if jurisdiction else subject.jurisdiction
