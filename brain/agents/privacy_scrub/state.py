"""Data access layer for privacy-scrub foundations.

This module deliberately accepts storage-safe values only. Callers must encrypt
payload bodies and compute keyed digests before writing to these tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg

from brain.agents.privacy_scrub.identity import IdentityTuple, TupleType
from brain.agents.privacy_scrub.subjects import Role, SubjectStatus
from brain.agents.privacy_scrub.targets import Target
from jarvis_common.logging_config import get_logger

logger = get_logger("privacy_scrub.state")


@dataclass(frozen=True, slots=True)
class StoredSubject:
    id: UUID
    user_id: str
    display_label_digest: str
    role: Role
    guardian_user_id: str | None
    jurisdiction: str
    status: SubjectStatus
    subject_payload_hash: str
    subject_payload_key_version: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


async def insert_subject(
    conn: asyncpg.Connection,
    *,
    user_id: str,
    display_label_digest: str,
    role: Role,
    subject_payload_ciphertext: bytes,
    subject_payload_hash: str,
    subject_payload_key_version: str,
    guardian_user_id: str | None = None,
    jurisdiction: str = "US_GA",
) -> UUID:
    if role == Role.MINOR and not guardian_user_id:
        raise ValueError("minor subject requires guardian_user_id")
    if not subject_payload_ciphertext:
        raise ValueError("subject_payload_ciphertext is required")

    row = await conn.fetchrow(
        """
        INSERT INTO public.alpha_privacy_subjects
            (user_id, display_label_digest, role, guardian_user_id,
             jurisdiction, subject_payload_ciphertext, subject_payload_hash,
             subject_payload_key_version)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id
        """,
        user_id,
        display_label_digest,
        role.value,
        guardian_user_id,
        jurisdiction,
        subject_payload_ciphertext,
        subject_payload_hash,
        subject_payload_key_version,
    )
    assert row is not None
    return row["id"]


async def get_subject(
    conn: asyncpg.Connection,
    subject_id: UUID,
) -> StoredSubject | None:
    row = await conn.fetchrow(
        """
        SELECT id, user_id, display_label_digest, role, guardian_user_id,
               jurisdiction, status, subject_payload_hash,
               subject_payload_key_version, created_at, updated_at
        FROM public.alpha_privacy_subjects
        WHERE id = $1
        """,
        subject_id,
    )
    return _row_to_stored_subject(row) if row else None


async def list_subjects_for_user(
    conn: asyncpg.Connection,
    user_id: str,
) -> list[StoredSubject]:
    rows = await conn.fetch(
        """
        SELECT id, user_id, display_label_digest, role, guardian_user_id,
               jurisdiction, status, subject_payload_hash,
               subject_payload_key_version, created_at, updated_at
        FROM public.alpha_privacy_subjects
        WHERE user_id = $1 OR guardian_user_id = $1
        ORDER BY created_at
        """,
        user_id,
    )
    return [_row_to_stored_subject(row) for row in rows]


async def update_subject_status(
    conn: asyncpg.Connection,
    subject_id: UUID,
    status: SubjectStatus,
) -> bool:
    result = await conn.execute(
        """
        UPDATE public.alpha_privacy_subjects
        SET status = $2
        WHERE id = $1
        """,
        subject_id,
        status.value,
    )
    return result.endswith(" 1")


async def insert_identity_tuple(
    conn: asyncpg.Connection,
    tuple_obj: IdentityTuple,
) -> UUID | None:
    row = await conn.fetchrow(
        """
        INSERT INTO public.alpha_privacy_identity_tuples
            (subject_id, tuple_type, digest, key_version, label_digest, active)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (subject_id, tuple_type, digest, key_version) DO NOTHING
        RETURNING id
        """,
        tuple_obj.subject_id,
        tuple_obj.tuple_type.value,
        tuple_obj.digest,
        tuple_obj.key_version,
        tuple_obj.label_digest,
        tuple_obj.active,
    )
    return row["id"] if row else None


async def list_identity_tuples(
    conn: asyncpg.Connection,
    subject_id: UUID,
    active_only: bool = True,
) -> list[IdentityTuple]:
    where = "WHERE subject_id = $1"
    if active_only:
        where += " AND active = TRUE"
    rows = await conn.fetch(
        f"""
        SELECT id, subject_id, tuple_type, digest, key_version, label_digest, active
        FROM public.alpha_privacy_identity_tuples
        {where}
        ORDER BY tuple_type, created_at
        """,
        subject_id,
    )
    return [
        IdentityTuple(
            id=row["id"],
            subject_id=row["subject_id"],
            tuple_type=TupleType(row["tuple_type"]),
            digest=row["digest"],
            key_version=row["key_version"],
            label_digest=row["label_digest"],
            active=row["active"],
        )
        for row in rows
    ]


async def refresh_targets_cache(
    conn: asyncpg.Connection,
    targets: list[Target],
    source_label: str = "yaml",
) -> int:
    async with conn.transaction():
        await conn.execute("DELETE FROM public.alpha_privacy_targets_cache")
        for target in targets:
            await conn.execute(
                """
                INSERT INTO public.alpha_privacy_targets_cache
                    (id, name, category, jurisdiction, opt_out_method,
                     opt_out_url, contact_email, supports_minors,
                     requires_sensitive_payload, requires_identity_document,
                     avg_response_days, last_verified, notes, yaml_source)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        $11, $12, $13, $14)
                """,
                target.id,
                target.name,
                target.category.value,
                target.jurisdiction.value,
                target.opt_out_method.value,
                target.opt_out_url,
                target.contact_email,
                target.supports_minors,
                target.requires_sensitive_payload,
                target.requires_identity_document,
                target.avg_response_days,
                target.last_verified,
                target.notes,
                source_label,
            )
    logger.info(
        "privacy_targets_cache_refreshed count=%d source=%s",
        len(targets),
        source_label,
    )
    return len(targets)


async def append_action_event(
    conn: asyncpg.Connection,
    *,
    action_id: UUID,
    event_type: str,
    actor: str,
    event_payload_ciphertext: bytes | None = None,
    event_payload_hash: str | None = None,
) -> UUID:
    row = await conn.fetchrow(
        """
        INSERT INTO public.alpha_privacy_action_events
            (action_id, event_type, actor, event_payload_ciphertext,
             event_payload_hash)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        action_id,
        event_type,
        actor,
        event_payload_ciphertext,
        event_payload_hash,
    )
    assert row is not None
    return row["id"]


async def count_targets(conn: asyncpg.Connection) -> int:
    return await conn.fetchval(
        "SELECT COUNT(*) FROM public.alpha_privacy_targets_cache"
    )


async def get_target(
    conn: asyncpg.Connection,
    target_id: str,
) -> dict[str, object] | None:
    row = await conn.fetchrow(
        """
        SELECT id, name, category, jurisdiction, opt_out_method,
               opt_out_url, contact_email, supports_minors,
               requires_sensitive_payload, requires_identity_document,
               avg_response_days, last_verified, notes, yaml_source
        FROM public.alpha_privacy_targets_cache
        WHERE id = $1
        """,
        target_id,
    )
    return dict(row) if row else None


def _row_to_stored_subject(row: asyncpg.Record) -> StoredSubject:
    return StoredSubject(
        id=row["id"],
        user_id=row["user_id"],
        display_label_digest=row["display_label_digest"],
        role=Role(row["role"]),
        guardian_user_id=row["guardian_user_id"],
        jurisdiction=row["jurisdiction"],
        status=SubjectStatus(row["status"]),
        subject_payload_hash=row["subject_payload_hash"],
        subject_payload_key_version=row["subject_payload_key_version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
