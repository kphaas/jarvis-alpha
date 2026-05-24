from __future__ import annotations

import os
from dataclasses import dataclass

import asyncpg

from brain.services.gmail_client import GmailMessage
from brain.services.school_email_parser import (
    SchoolActionCandidate,
    SchoolEventCandidate,
)
from brain.services.school_email_rules import SchoolEmailScanRule


@dataclass(frozen=True)
class PersistedCandidate:
    id: str
    created: bool
    status: str
    family_id: str | None


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").strip()
    return message[:240] or exc.__class__.__name__


async def start_scan_run(
    conn: asyncpg.Connection,
    *,
    trigger: str,
    lookback_days: int,
    max_results: int,
    import_to_family: bool,
    manual_query: bool,
) -> str:
    return str(
        await conn.fetchval(
            """
            INSERT INTO public.alpha_school_email_scan_runs (
                trigger, lookback_days, max_results, import_to_family, manual_query
            )
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            trigger,
            lookback_days,
            max_results,
            import_to_family,
            manual_query,
        )
    )


async def finish_scan_run(conn: asyncpg.Connection, scan_run_id: str, result) -> None:
    await conn.execute(
        """
        UPDATE public.alpha_school_email_scan_runs
        SET status = 'succeeded',
            finished_at = now(),
            rules_loaded = $2,
            queries_run = $3,
            messages_seen = $4,
            messages_new = $5,
            event_candidates_created = $6,
            action_candidates_created = $7,
            events_imported = $8,
            actions_imported = $9,
            import_errors = $10,
            updated_at = now()
        WHERE id = $1::uuid
        """,
        scan_run_id,
        result.rules_loaded,
        result.queries_run,
        result.messages_seen,
        result.messages_new,
        result.event_candidates_created,
        result.action_candidates_created,
        result.events_imported,
        result.actions_imported,
        result.import_errors,
    )


async def fail_scan_run(
    conn: asyncpg.Connection,
    scan_run_id: str,
    exc: Exception,
) -> None:
    await conn.execute(
        """
        UPDATE public.alpha_school_email_scan_runs
        SET status = 'failed',
            finished_at = now(),
            error_type = $2,
            error_message = $3,
            updated_at = now()
        WHERE id = $1::uuid
        """,
        scan_run_id,
        exc.__class__.__name__,
        _safe_error_message(exc),
    )


async def latest_scan_run(conn: asyncpg.Connection):
    return await conn.fetchrow(
        """
        SELECT id, trigger, status, started_at, finished_at, lookback_days,
               max_results, import_to_family, manual_query, rules_loaded,
               queries_run, messages_seen, messages_new,
               event_candidates_created, action_candidates_created,
               events_imported, actions_imported, import_errors,
               error_type, error_message
        FROM public.alpha_school_email_scan_runs
        ORDER BY started_at DESC
        LIMIT 1
        """
    )


async def message_exists(conn: asyncpg.Connection, gmail_message_id: str) -> bool:
    return bool(
        await conn.fetchval(
            """
            SELECT 1
            FROM public.alpha_school_email_messages
            WHERE gmail_message_id = $1
            """,
            gmail_message_id,
        )
    )


async def record_message(
    conn: asyncpg.Connection,
    message: GmailMessage,
    rule: SchoolEmailScanRule | None,
) -> str:
    return str(
        await conn.fetchval(
            """
            INSERT INTO public.alpha_school_email_messages (
                gmail_message_id, gmail_thread_id, history_id, sender, subject,
                received_at, snippet, body_sha256, classification,
                family_rule_id, child_member_id, child_name
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'school',$9,$10::uuid,$11)
            ON CONFLICT (gmail_message_id) DO UPDATE
            SET gmail_thread_id = EXCLUDED.gmail_thread_id,
                history_id = EXCLUDED.history_id,
                sender = EXCLUDED.sender,
                subject = EXCLUDED.subject,
                received_at = EXCLUDED.received_at,
                snippet = EXCLUDED.snippet,
                body_sha256 = EXCLUDED.body_sha256,
                family_rule_id = COALESCE(
                    EXCLUDED.family_rule_id,
                    alpha_school_email_messages.family_rule_id
                ),
                child_member_id = COALESCE(
                    EXCLUDED.child_member_id,
                    alpha_school_email_messages.child_member_id
                ),
                child_name = COALESCE(
                    EXCLUDED.child_name,
                    alpha_school_email_messages.child_name
                ),
                processed_at = now(),
                updated_at = now()
            RETURNING id
            """,
            message.gmail_message_id,
            message.thread_id,
            message.history_id,
            message.sender,
            message.subject,
            message.received_at,
            message.snippet,
            message.body_sha256,
            rule.id if rule else None,
            rule.child_member_id if rule else None,
            rule.child_name if rule else None,
        )
    )


def _candidate_status(confidence: float) -> str:
    auto_threshold = os.environ.get("ALPHA_SCHOOL_EMAIL_AUTO_APPROVE_MIN_CONFIDENCE")
    if not auto_threshold:
        return "needs_review"
    try:
        return "approved" if confidence >= float(auto_threshold) else "needs_review"
    except ValueError:
        return "needs_review"


async def record_event_candidate(
    conn: asyncpg.Connection,
    message_id: str,
    gmail_message_id: str,
    candidate: SchoolEventCandidate,
) -> PersistedCandidate:
    row = await conn.fetchrow(
        """
        INSERT INTO public.alpha_school_event_candidates (
            email_message_id, gmail_message_id, title, event_date, event_time,
            end_time, location, notes, confidence, family_external_id, status,
            child_member_id, child_name
        )
        VALUES ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::uuid,$13)
        ON CONFLICT (family_external_id) DO NOTHING
        RETURNING id, status, family_event_id
        """,
        message_id,
        gmail_message_id,
        candidate.title,
        candidate.event_date,
        candidate.event_time,
        candidate.end_time,
        candidate.location,
        candidate.notes,
        candidate.confidence,
        candidate.family_external_id,
        _candidate_status(candidate.confidence),
        candidate.child_member_id,
        candidate.child_name,
    )
    if row is not None:
        return _event_persisted(row, created=True)
    row = await conn.fetchrow(
        """
        SELECT id, status, family_event_id
        FROM public.alpha_school_event_candidates
        WHERE family_external_id = $1
        """,
        candidate.family_external_id,
    )
    return _event_persisted(row, created=False)


async def record_action_candidate(
    conn: asyncpg.Connection,
    message_id: str,
    gmail_message_id: str,
    candidate: SchoolActionCandidate,
) -> PersistedCandidate:
    row = await conn.fetchrow(
        """
        INSERT INTO public.alpha_school_action_candidates (
            email_message_id, gmail_message_id, title, action_date, action_time,
            notes, confidence, family_external_id, status, child_member_id,
            child_name
        )
        VALUES ($1::uuid,$2,$3,$4,$5,$6,$7,$8,$9,$10::uuid,$11)
        ON CONFLICT (family_external_id) DO NOTHING
        RETURNING id, status, family_action_id
        """,
        message_id,
        gmail_message_id,
        candidate.title,
        candidate.action_date,
        candidate.action_time,
        candidate.notes,
        candidate.confidence,
        candidate.family_external_id,
        _candidate_status(candidate.confidence),
        candidate.child_member_id,
        candidate.child_name,
    )
    if row is not None:
        return _action_persisted(row, created=True)
    row = await conn.fetchrow(
        """
        SELECT id, status, family_action_id
        FROM public.alpha_school_action_candidates
        WHERE family_external_id = $1
        """,
        candidate.family_external_id,
    )
    return _action_persisted(row, created=False)


def _event_persisted(row, *, created: bool) -> PersistedCandidate:
    return PersistedCandidate(
        id=str(row["id"]),
        created=created,
        status=row["status"],
        family_id=str(row["family_event_id"]) if row["family_event_id"] else None,
    )


def _action_persisted(row, *, created: bool) -> PersistedCandidate:
    return PersistedCandidate(
        id=str(row["id"]),
        created=created,
        status=row["status"],
        family_id=str(row["family_action_id"]) if row["family_action_id"] else None,
    )
