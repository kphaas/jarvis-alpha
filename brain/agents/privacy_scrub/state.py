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


@dataclass(frozen=True, slots=True)
class StoredCaseDraft:
    id: UUID
    subject_id: UUID
    created_by_user_id: str
    target_count: int
    status: str
    packet_payload_hash: str
    payload_key_version: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StoredCaseDraftListItem:
    case_draft: StoredCaseDraft
    action_count: int
    approval_tiers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StoredCaseDraftPayload:
    case_draft: StoredCaseDraft
    packet_payload_ciphertext: bytes


@dataclass(frozen=True, slots=True)
class StoredDraftAction:
    id: UUID
    subject_id: UUID
    target_id: str
    case_draft_id: UUID
    action_type: str
    approval_tier: str
    status: str
    draft_payload_hash: str | None
    payload_key_version: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StoredApprovedPrivacyAction:
    id: UUID
    subject_id: UUID
    target_id: str
    case_draft_id: UUID
    action_type: str
    approval_tier: str
    status: str
    approval_queue_id: UUID | None
    draft_payload_hash: str | None
    payload_key_version: str | None
    target_name: str
    target_category: str
    target_jurisdiction: str
    target_opt_out_method: str
    target_avg_response_days: int | None
    case_status: str
    case_created_at: datetime | None
    approved_at: datetime | None
    manual_disposition: str | None = None
    manual_disposition_at: datetime | None = None
    manual_disposition_by: str | None = None
    manual_note_hash: str | None = None
    evidence_payload_hash: str | None = None
    workflow_payload_key_version: str | None = None
    sent_at: datetime | None = None
    confirmed_at: datetime | None = None
    verification_due_at: datetime | None = None
    error_code: str | None = None
    error_digest: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StoredPrivacyActionEvent:
    id: UUID
    action_id: UUID
    case_draft_id: UUID
    target_id: str
    target_name: str
    event_type: str
    actor: str
    event_payload_hash: str | None
    created_at: datetime | None


_CASE_DRAFT_STATUSES = {
    "draft",
    "submitted_for_approval",
    "archived",
    "completed",
}
_MANUAL_DISPOSITIONS = {"handled", "deferred", "blocked"}
_VERIFICATION_OUTCOMES = {"confirmed", "needs_followup", "failed"}


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


async def insert_case_draft(
    conn: asyncpg.Connection,
    *,
    subject_id: UUID,
    created_by_user_id: str,
    target_count: int,
    packet_payload_ciphertext: bytes,
    packet_payload_hash: str,
    payload_key_version: str,
) -> StoredCaseDraft:
    if target_count < 1:
        raise ValueError("target_count must be positive")
    if not created_by_user_id.strip():
        raise ValueError("created_by_user_id is required")
    if not packet_payload_ciphertext:
        raise ValueError("packet_payload_ciphertext is required")

    row = await conn.fetchrow(
        """
        INSERT INTO public.alpha_privacy_case_drafts
            (subject_id, created_by_user_id, target_count,
             packet_payload_ciphertext, packet_payload_hash, payload_key_version)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, subject_id, created_by_user_id, target_count, status,
                  packet_payload_hash, payload_key_version, created_at, updated_at
        """,
        subject_id,
        created_by_user_id,
        target_count,
        packet_payload_ciphertext,
        packet_payload_hash,
        payload_key_version,
    )
    assert row is not None
    return _row_to_stored_case_draft(row)


async def list_case_drafts(
    conn: asyncpg.Connection,
    *,
    limit: int = 25,
) -> list[StoredCaseDraftListItem]:
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")

    rows = await conn.fetch(
        """
        SELECT
            c.id, c.subject_id, c.created_by_user_id, c.target_count,
            c.status, c.packet_payload_hash, c.payload_key_version,
            c.created_at, c.updated_at,
            COUNT(a.id)::INTEGER AS action_count,
            ARRAY_REMOVE(
                ARRAY_AGG(DISTINCT a.approval_tier ORDER BY a.approval_tier),
                NULL
            ) AS approval_tiers
        FROM public.alpha_privacy_case_drafts c
        LEFT JOIN public.alpha_privacy_actions a
            ON a.case_draft_id = c.id
        GROUP BY
            c.id, c.subject_id, c.created_by_user_id, c.target_count,
            c.status, c.packet_payload_hash, c.payload_key_version,
            c.created_at, c.updated_at
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT $1
        """,
        limit,
    )
    return [_row_to_stored_case_draft_list_item(row) for row in rows]


async def get_case_draft_payload(
    conn: asyncpg.Connection,
    case_draft_id: UUID,
) -> StoredCaseDraftPayload | None:
    row = await conn.fetchrow(
        """
        SELECT id, subject_id, created_by_user_id, target_count, status,
               packet_payload_ciphertext, packet_payload_hash,
               payload_key_version, created_at, updated_at
        FROM public.alpha_privacy_case_drafts
        WHERE id = $1
        """,
        case_draft_id,
    )
    return _row_to_stored_case_draft_payload(row) if row else None


async def get_case_draft(
    conn: asyncpg.Connection,
    case_draft_id: UUID,
) -> StoredCaseDraft | None:
    row = await conn.fetchrow(
        """
        SELECT id, subject_id, created_by_user_id, target_count, status,
               packet_payload_hash, payload_key_version, created_at, updated_at
        FROM public.alpha_privacy_case_drafts
        WHERE id = $1
        """,
        case_draft_id,
    )
    return _row_to_stored_case_draft(row) if row else None


async def insert_draft_action(
    conn: asyncpg.Connection,
    *,
    subject_id: UUID,
    target_id: str,
    case_draft_id: UUID,
    action_type: str,
    approval_tier: str,
    draft_payload_ciphertext: bytes,
    draft_payload_hash: str,
    payload_key_version: str,
) -> StoredDraftAction:
    if not target_id.strip():
        raise ValueError("target_id is required")
    if action_type != "draft":
        raise ValueError("P2-E only creates draft actions")
    if not draft_payload_ciphertext:
        raise ValueError("draft_payload_ciphertext is required")

    row = await conn.fetchrow(
        """
        INSERT INTO public.alpha_privacy_actions
            (subject_id, target_id, case_draft_id, action_type, approval_tier,
             status, draft_payload_ciphertext, draft_payload_hash,
             payload_key_version)
        VALUES ($1, $2, $3, $4, $5, 'pending', $6, $7, $8)
        RETURNING id, subject_id, target_id, case_draft_id, action_type,
                  approval_tier, status, draft_payload_hash,
                  payload_key_version, created_at, updated_at
        """,
        subject_id,
        target_id,
        case_draft_id,
        action_type,
        approval_tier,
        draft_payload_ciphertext,
        draft_payload_hash,
        payload_key_version,
    )
    assert row is not None
    return _row_to_stored_draft_action(row)


async def list_draft_actions_for_case(
    conn: asyncpg.Connection,
    case_draft_id: UUID,
) -> list[StoredDraftAction]:
    rows = await conn.fetch(
        """
        SELECT id, subject_id, target_id, case_draft_id, action_type,
               approval_tier, status, draft_payload_hash,
               payload_key_version, created_at, updated_at
        FROM public.alpha_privacy_actions
        WHERE case_draft_id = $1
        ORDER BY created_at, target_id, id
        """,
        case_draft_id,
    )
    return [_row_to_stored_draft_action(row) for row in rows]


async def list_approved_privacy_actions(
    conn: asyncpg.Connection,
    *,
    limit: int = 25,
) -> list[StoredApprovedPrivacyAction]:
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")

    rows = await conn.fetch(
        """
        SELECT
            a.id, a.subject_id, a.target_id, a.case_draft_id, a.action_type,
            a.approval_tier, a.status, a.approval_queue_id,
            a.draft_payload_hash, a.payload_key_version,
            a.manual_disposition, a.manual_disposition_at,
            a.manual_disposition_by, a.manual_note_hash,
            a.evidence_payload_hash, a.workflow_payload_key_version,
            a.sent_at, a.confirmed_at, a.verification_due_at,
            a.error_code, a.error_digest,
            a.created_at, a.updated_at,
            t.name AS target_name,
            t.category AS target_category,
            t.jurisdiction AS target_jurisdiction,
            t.opt_out_method AS target_opt_out_method,
            t.avg_response_days AS target_avg_response_days,
            c.status AS case_status,
            c.created_at AS case_created_at,
            COALESCE(approved_event.created_at, a.updated_at) AS approved_at
        FROM public.alpha_privacy_actions AS a
        JOIN public.alpha_privacy_case_drafts AS c
          ON c.id = a.case_draft_id
        JOIN public.alpha_privacy_targets_cache AS t
          ON t.id = a.target_id
        LEFT JOIN LATERAL (
            SELECT e.created_at
            FROM public.alpha_privacy_action_events AS e
            WHERE e.action_id = a.id
              AND e.event_type = 'approved'
            ORDER BY e.created_at DESC, e.id DESC
            LIMIT 1
        ) AS approved_event ON TRUE
        WHERE a.status IN ('approved', 'sent', 'confirmed', 'failed')
          AND a.approval_queue_id IS NOT NULL
        ORDER BY approved_at DESC NULLS LAST, a.created_at DESC, a.id DESC
        LIMIT $1
        """,
        limit,
    )
    return [_row_to_stored_approved_privacy_action(row) for row in rows]


async def update_privacy_action_manual_disposition(
    conn: asyncpg.Connection,
    *,
    action_id: UUID,
    disposition: str,
    actor: str,
    manual_note_ciphertext: bytes | None = None,
    manual_note_hash: str | None = None,
    evidence_payload_ciphertext: bytes | None = None,
    evidence_payload_hash: str | None = None,
    workflow_payload_key_version: str | None = None,
    verification_due_at: datetime | None = None,
) -> StoredApprovedPrivacyAction | None:
    if disposition not in _MANUAL_DISPOSITIONS:
        raise ValueError("invalid privacy action manual disposition")
    if not actor.strip():
        raise ValueError("manual disposition actor is required")

    status = {
        "handled": "sent",
        "deferred": "approved",
        "blocked": "failed",
    }[disposition]

    row = await conn.fetchrow(
        """
        WITH updated AS (
            UPDATE public.alpha_privacy_actions
            SET status = $2,
                manual_disposition = $3,
                manual_disposition_at = NOW(),
                manual_disposition_by = $4,
                manual_note_ciphertext = $5,
                manual_note_hash = $6,
                evidence_payload_ciphertext = $7,
                evidence_payload_hash = $8,
                workflow_payload_key_version = $9,
                sent_at = CASE
                    WHEN $3 = 'handled' THEN COALESCE(sent_at, NOW())
                    ELSE sent_at
                END,
                verification_due_at = CASE
                    WHEN $3 IN ('handled', 'deferred') THEN $10::timestamptz
                    ELSE verification_due_at
                END,
                error_code = CASE
                    WHEN $3 = 'blocked' THEN 'manual_blocked'
                    ELSE error_code
                END,
                error_digest = CASE
                    WHEN $3 = 'blocked' THEN COALESCE($8, $6, error_digest)
                    ELSE error_digest
                END
            WHERE id = $1
              AND status IN ('approved', 'sent')
              AND approval_queue_id IS NOT NULL
            RETURNING *
        )
        SELECT
            a.id, a.subject_id, a.target_id, a.case_draft_id, a.action_type,
            a.approval_tier, a.status, a.approval_queue_id,
            a.draft_payload_hash, a.payload_key_version,
            a.manual_disposition, a.manual_disposition_at,
            a.manual_disposition_by, a.manual_note_hash,
            a.evidence_payload_hash, a.workflow_payload_key_version,
            a.sent_at, a.confirmed_at, a.verification_due_at,
            a.error_code, a.error_digest,
            a.created_at, a.updated_at,
            t.name AS target_name,
            t.category AS target_category,
            t.jurisdiction AS target_jurisdiction,
            t.opt_out_method AS target_opt_out_method,
            t.avg_response_days AS target_avg_response_days,
            c.status AS case_status,
            c.created_at AS case_created_at,
            COALESCE(approved_event.created_at, a.updated_at) AS approved_at
        FROM updated AS a
        JOIN public.alpha_privacy_case_drafts AS c
          ON c.id = a.case_draft_id
        JOIN public.alpha_privacy_targets_cache AS t
          ON t.id = a.target_id
        LEFT JOIN LATERAL (
            SELECT e.created_at
            FROM public.alpha_privacy_action_events AS e
            WHERE e.action_id = a.id
              AND e.event_type = 'approved'
            ORDER BY e.created_at DESC, e.id DESC
            LIMIT 1
        ) AS approved_event ON TRUE
        """,
        action_id,
        status,
        disposition,
        actor,
        manual_note_ciphertext,
        manual_note_hash,
        evidence_payload_ciphertext,
        evidence_payload_hash,
        workflow_payload_key_version,
        verification_due_at,
    )
    return _row_to_stored_approved_privacy_action(row) if row else None


async def update_privacy_action_verification(
    conn: asyncpg.Connection,
    *,
    action_id: UUID,
    outcome: str,
    actor: str,
    evidence_payload_ciphertext: bytes | None = None,
    evidence_payload_hash: str | None = None,
    workflow_payload_key_version: str | None = None,
    verification_due_at: datetime | None = None,
) -> StoredApprovedPrivacyAction | None:
    if outcome not in _VERIFICATION_OUTCOMES:
        raise ValueError("invalid privacy action verification outcome")
    if not actor.strip():
        raise ValueError("verification actor is required")

    status = {
        "confirmed": "confirmed",
        "needs_followup": "sent",
        "failed": "failed",
    }[outcome]

    row = await conn.fetchrow(
        """
        WITH updated AS (
            UPDATE public.alpha_privacy_actions
            SET status = $2,
                manual_disposition = COALESCE(manual_disposition, 'handled'),
                evidence_payload_ciphertext = COALESCE($4, evidence_payload_ciphertext),
                evidence_payload_hash = COALESCE($5, evidence_payload_hash),
                workflow_payload_key_version = COALESCE(
                    $6,
                    workflow_payload_key_version
                ),
                sent_at = CASE
                    WHEN $3 IN ('confirmed', 'needs_followup')
                        THEN COALESCE(sent_at, NOW())
                    ELSE sent_at
                END,
                confirmed_at = CASE
                    WHEN $3 = 'confirmed' THEN NOW()
                    ELSE confirmed_at
                END,
                verification_due_at = CASE
                    WHEN $3 = 'needs_followup' THEN $7::timestamptz
                    ELSE NULL::timestamptz
                END,
                error_code = CASE
                    WHEN $3 = 'failed' THEN 'verification_failed'
                    ELSE error_code
                END,
                error_digest = CASE
                    WHEN $3 = 'failed' THEN COALESCE($5, error_digest)
                    ELSE error_digest
                END
            WHERE id = $1
              AND status IN ('approved', 'sent', 'failed')
              AND approval_queue_id IS NOT NULL
            RETURNING *
        )
        SELECT
            a.id, a.subject_id, a.target_id, a.case_draft_id, a.action_type,
            a.approval_tier, a.status, a.approval_queue_id,
            a.draft_payload_hash, a.payload_key_version,
            a.manual_disposition, a.manual_disposition_at,
            a.manual_disposition_by, a.manual_note_hash,
            a.evidence_payload_hash, a.workflow_payload_key_version,
            a.sent_at, a.confirmed_at, a.verification_due_at,
            a.error_code, a.error_digest,
            a.created_at, a.updated_at,
            t.name AS target_name,
            t.category AS target_category,
            t.jurisdiction AS target_jurisdiction,
            t.opt_out_method AS target_opt_out_method,
            t.avg_response_days AS target_avg_response_days,
            c.status AS case_status,
            c.created_at AS case_created_at,
            COALESCE(approved_event.created_at, a.updated_at) AS approved_at
        FROM updated AS a
        JOIN public.alpha_privacy_case_drafts AS c
          ON c.id = a.case_draft_id
        JOIN public.alpha_privacy_targets_cache AS t
          ON t.id = a.target_id
        LEFT JOIN LATERAL (
            SELECT e.created_at
            FROM public.alpha_privacy_action_events AS e
            WHERE e.action_id = a.id
              AND e.event_type = 'approved'
            ORDER BY e.created_at DESC, e.id DESC
            LIMIT 1
        ) AS approved_event ON TRUE
        """,
        action_id,
        status,
        outcome,
        evidence_payload_ciphertext,
        evidence_payload_hash,
        workflow_payload_key_version,
        verification_due_at,
    )
    return _row_to_stored_approved_privacy_action(row) if row else None


async def list_privacy_actions_for_case(
    conn: asyncpg.Connection,
    *,
    case_draft_id: UUID,
) -> list[StoredApprovedPrivacyAction]:
    rows = await conn.fetch(
        """
        SELECT
            a.id, a.subject_id, a.target_id, a.case_draft_id, a.action_type,
            a.approval_tier, a.status, a.approval_queue_id,
            a.draft_payload_hash, a.payload_key_version,
            a.manual_disposition, a.manual_disposition_at,
            a.manual_disposition_by, a.manual_note_hash,
            a.evidence_payload_hash, a.workflow_payload_key_version,
            a.sent_at, a.confirmed_at, a.verification_due_at,
            a.error_code, a.error_digest,
            a.created_at, a.updated_at,
            t.name AS target_name,
            t.category AS target_category,
            t.jurisdiction AS target_jurisdiction,
            t.opt_out_method AS target_opt_out_method,
            t.avg_response_days AS target_avg_response_days,
            c.status AS case_status,
            c.created_at AS case_created_at,
            COALESCE(approved_event.created_at, a.updated_at) AS approved_at
        FROM public.alpha_privacy_actions AS a
        JOIN public.alpha_privacy_case_drafts AS c
          ON c.id = a.case_draft_id
        JOIN public.alpha_privacy_targets_cache AS t
          ON t.id = a.target_id
        LEFT JOIN LATERAL (
            SELECT e.created_at
            FROM public.alpha_privacy_action_events AS e
            WHERE e.action_id = a.id
              AND e.event_type = 'approved'
            ORDER BY e.created_at DESC, e.id DESC
            LIMIT 1
        ) AS approved_event ON TRUE
        WHERE a.case_draft_id = $1
        ORDER BY t.category, t.name, a.created_at, a.id
        """,
        case_draft_id,
    )
    return [_row_to_stored_approved_privacy_action(row) for row in rows]


async def list_privacy_action_events_for_case(
    conn: asyncpg.Connection,
    *,
    case_draft_id: UUID,
) -> list[StoredPrivacyActionEvent]:
    rows = await conn.fetch(
        """
        SELECT
            e.id, e.action_id, a.case_draft_id, a.target_id,
            t.name AS target_name, e.event_type, e.actor,
            e.event_payload_hash, e.created_at
        FROM public.alpha_privacy_action_events AS e
        JOIN public.alpha_privacy_actions AS a
          ON a.id = e.action_id
        JOIN public.alpha_privacy_targets_cache AS t
          ON t.id = a.target_id
        WHERE a.case_draft_id = $1
        ORDER BY e.created_at, e.id
        """,
        case_draft_id,
    )
    return [_row_to_stored_privacy_action_event(row) for row in rows]


async def enqueue_approval_request(
    conn: asyncpg.Connection,
    *,
    action_classes: tuple[str, ...],
    risk_tier: str,
    actor_sub: str,
    actor_type: str,
    description: str,
    parameters_hash: str,
    nonce: str,
) -> UUID:
    if risk_tier not in {"T1", "T2", "T3", "T4", "T5"}:
        raise ValueError("risk_tier must be a valid approval tier")
    if not action_classes:
        raise ValueError("action_classes is required")
    if not actor_sub.strip():
        raise ValueError("actor_sub is required")
    if not description.strip():
        raise ValueError("description is required")
    if not parameters_hash.strip():
        raise ValueError("parameters_hash is required")
    if not nonce.strip():
        raise ValueError("nonce is required")

    queue_id = await conn.fetchval(
        """
        SELECT public.enqueue_approval_request(
            $1::text[], $2, $3, $4, $5, $6, $7
        )
        """,
        list(action_classes),
        risk_tier,
        actor_sub,
        actor_type,
        description,
        parameters_hash,
        nonce,
    )
    assert queue_id is not None
    return queue_id


async def update_case_draft_status(
    conn: asyncpg.Connection,
    *,
    case_draft_id: UUID,
    status: str,
    expected_statuses: tuple[str, ...] = ("draft",),
) -> StoredCaseDraft | None:
    if status not in _CASE_DRAFT_STATUSES:
        raise ValueError("invalid case draft status")
    if not expected_statuses or any(
        expected not in _CASE_DRAFT_STATUSES for expected in expected_statuses
    ):
        raise ValueError("invalid expected case draft status")

    row = await conn.fetchrow(
        """
        UPDATE public.alpha_privacy_case_drafts
        SET status = $2
        WHERE id = $1
          AND status = ANY($3::text[])
        RETURNING id, subject_id, created_by_user_id, target_count, status,
                  packet_payload_hash, payload_key_version, created_at, updated_at
        """,
        case_draft_id,
        status,
        list(expected_statuses),
    )
    return _row_to_stored_case_draft(row) if row else None


async def mark_case_draft_completed_if_terminal(
    conn: asyncpg.Connection,
    *,
    case_draft_id: UUID,
) -> StoredCaseDraft | None:
    row = await conn.fetchrow(
        """
        WITH action_summary AS (
            SELECT
                COUNT(*)::int AS action_count,
                COUNT(*) FILTER (
                    WHERE status IN ('confirmed', 'failed')
                )::int AS terminal_count
            FROM public.alpha_privacy_actions
            WHERE case_draft_id = $1
              AND approval_queue_id IS NOT NULL
        ),
        updated AS (
            UPDATE public.alpha_privacy_case_drafts
            SET status = 'completed'
            WHERE id = $1
              AND status = 'submitted_for_approval'
              AND EXISTS (
                  SELECT 1
                  FROM action_summary
                  WHERE action_count > 0
                    AND terminal_count = action_count
              )
            RETURNING id, subject_id, created_by_user_id, target_count, status,
                      packet_payload_hash, payload_key_version,
                      created_at, updated_at
        )
        SELECT id, subject_id, created_by_user_id, target_count, status,
               packet_payload_hash, payload_key_version, created_at, updated_at
        FROM updated
        """,
        case_draft_id,
    )
    return _row_to_stored_case_draft(row) if row else None


async def mark_case_actions_awaiting_approval(
    conn: asyncpg.Connection,
    *,
    case_draft_id: UUID,
    approval_queue_id: UUID,
) -> list[StoredDraftAction]:
    rows = await conn.fetch(
        """
        UPDATE public.alpha_privacy_actions
        SET status = 'awaiting_approval',
            approval_queue_id = $2
        WHERE case_draft_id = $1
          AND status = 'pending'
        RETURNING id, subject_id, target_id, case_draft_id, action_type,
                  approval_tier, status, draft_payload_hash,
                  payload_key_version, created_at, updated_at
        """,
        case_draft_id,
        approval_queue_id,
    )
    return [_row_to_stored_draft_action(row) for row in rows]


async def mark_approval_queue_actions_decided(
    conn: asyncpg.Connection,
    *,
    approval_queue_id: UUID,
    status: str,
) -> list[StoredDraftAction]:
    if status not in {"approved", "rejected"}:
        raise ValueError(
            "privacy approval decision status must be approved or rejected"
        )

    rows = await conn.fetch(
        """
        UPDATE public.alpha_privacy_actions
        SET status = $2
        WHERE approval_queue_id = $1
          AND status = 'awaiting_approval'
        RETURNING id, subject_id, target_id, case_draft_id, action_type,
                  approval_tier, status, draft_payload_hash,
                  payload_key_version, created_at, updated_at
        """,
        approval_queue_id,
        status,
    )
    return [_row_to_stored_draft_action(row) for row in rows]


async def reject_pending_case_actions(
    conn: asyncpg.Connection,
    *,
    case_draft_id: UUID,
) -> list[StoredDraftAction]:
    rows = await conn.fetch(
        """
        UPDATE public.alpha_privacy_actions
        SET status = 'rejected'
        WHERE case_draft_id = $1
          AND status = 'pending'
        RETURNING id, subject_id, target_id, case_draft_id, action_type,
                  approval_tier, status, draft_payload_hash,
                  payload_key_version, created_at, updated_at
        """,
        case_draft_id,
    )
    return [_row_to_stored_draft_action(row) for row in rows]


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
        await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
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
    async with conn.transaction():
        await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
        return await conn.fetchval(
            "SELECT COUNT(*) FROM public.alpha_privacy_targets_cache"
        )


async def get_target(
    conn: asyncpg.Connection,
    target_id: str,
) -> dict[str, object] | None:
    async with conn.transaction():
        await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
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


async def list_targets(conn: asyncpg.Connection) -> list[dict[str, object]]:
    async with conn.transaction():
        await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
        rows = await conn.fetch(
            """
            SELECT id, name, category, jurisdiction, opt_out_method,
                   opt_out_url, contact_email, supports_minors,
                   requires_sensitive_payload, requires_identity_document,
                   avg_response_days, last_verified, notes, yaml_source,
                   loaded_at
            FROM public.alpha_privacy_targets_cache
            ORDER BY category, jurisdiction, name, id
            """
        )
    return [dict(row) for row in rows]


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


def _row_to_stored_case_draft(row: asyncpg.Record) -> StoredCaseDraft:
    return StoredCaseDraft(
        id=row["id"],
        subject_id=row["subject_id"],
        created_by_user_id=row["created_by_user_id"],
        target_count=row["target_count"],
        status=row["status"],
        packet_payload_hash=row["packet_payload_hash"],
        payload_key_version=row["payload_key_version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_stored_case_draft_list_item(
    row: asyncpg.Record,
) -> StoredCaseDraftListItem:
    return StoredCaseDraftListItem(
        case_draft=_row_to_stored_case_draft(row),
        action_count=row["action_count"],
        approval_tiers=tuple(row["approval_tiers"] or ()),
    )


def _row_to_stored_case_draft_payload(
    row: asyncpg.Record,
) -> StoredCaseDraftPayload:
    return StoredCaseDraftPayload(
        case_draft=_row_to_stored_case_draft(row),
        packet_payload_ciphertext=row["packet_payload_ciphertext"],
    )


def _row_to_stored_draft_action(row: asyncpg.Record) -> StoredDraftAction:
    return StoredDraftAction(
        id=row["id"],
        subject_id=row["subject_id"],
        target_id=row["target_id"],
        case_draft_id=row["case_draft_id"],
        action_type=row["action_type"],
        approval_tier=row["approval_tier"],
        status=row["status"],
        draft_payload_hash=row["draft_payload_hash"],
        payload_key_version=row["payload_key_version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_stored_approved_privacy_action(
    row: asyncpg.Record,
) -> StoredApprovedPrivacyAction:
    return StoredApprovedPrivacyAction(
        id=row["id"],
        subject_id=row["subject_id"],
        target_id=row["target_id"],
        case_draft_id=row["case_draft_id"],
        action_type=row["action_type"],
        approval_tier=row["approval_tier"],
        status=row["status"],
        approval_queue_id=row["approval_queue_id"],
        draft_payload_hash=row["draft_payload_hash"],
        payload_key_version=row["payload_key_version"],
        target_name=row["target_name"],
        target_category=row["target_category"],
        target_jurisdiction=row["target_jurisdiction"],
        target_opt_out_method=row["target_opt_out_method"],
        target_avg_response_days=row["target_avg_response_days"],
        case_status=row["case_status"],
        case_created_at=row["case_created_at"],
        approved_at=row["approved_at"],
        manual_disposition=row["manual_disposition"],
        manual_disposition_at=row["manual_disposition_at"],
        manual_disposition_by=row["manual_disposition_by"],
        manual_note_hash=row["manual_note_hash"],
        evidence_payload_hash=row["evidence_payload_hash"],
        workflow_payload_key_version=row["workflow_payload_key_version"],
        sent_at=row["sent_at"],
        confirmed_at=row["confirmed_at"],
        verification_due_at=row["verification_due_at"],
        error_code=row["error_code"],
        error_digest=row["error_digest"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_stored_privacy_action_event(
    row: asyncpg.Record,
) -> StoredPrivacyActionEvent:
    return StoredPrivacyActionEvent(
        id=row["id"],
        action_id=row["action_id"],
        case_draft_id=row["case_draft_id"],
        target_id=row["target_id"],
        target_name=row["target_name"],
        event_type=row["event_type"],
        actor=row["actor"],
        event_payload_hash=row["event_payload_hash"],
        created_at=row["created_at"],
    )
