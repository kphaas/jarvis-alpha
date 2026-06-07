from __future__ import annotations

from dataclasses import dataclass

import asyncpg

from brain.services.at0_mail_classifier import MailClassification
from brain.services.at0_mail_graph_client import At0MailMessage


@dataclass(frozen=True)
class PersistedAt0Message:
    id: str
    created: bool
    status: str
    classification: str


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").strip()
    return message[:240] or exc.__class__.__name__


async def start_scan_run(
    conn: asyncpg.Connection,
    *,
    trigger: str,
    mailbox_count: int,
    max_results: int,
) -> str:
    return str(
        await conn.fetchval(
            """
            INSERT INTO public.alpha_at0_mail_scan_runs (
                trigger, mailbox_count, max_results
            )
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            trigger,
            mailbox_count,
            max_results,
        )
    )


async def finish_scan_run(conn: asyncpg.Connection, scan_run_id: str, result) -> None:
    await conn.execute(
        """
        UPDATE public.alpha_at0_mail_scan_runs
        SET status = 'succeeded',
            finished_at = now(),
            messages_seen = $2,
            messages_new = $3,
            draft_proposals_created = $4,
            updated_at = now()
        WHERE id = $1::uuid
        """,
        scan_run_id,
        result.messages_seen,
        result.messages_new,
        result.draft_proposals_created,
    )


async def fail_scan_run(
    conn: asyncpg.Connection,
    scan_run_id: str,
    exc: Exception,
) -> None:
    await conn.execute(
        """
        UPDATE public.alpha_at0_mail_scan_runs
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
        SELECT id, trigger, status, started_at, finished_at, mailbox_count,
               max_results, messages_seen, messages_new, draft_proposals_created,
               error_type, error_message
        FROM public.alpha_at0_mail_scan_runs
        ORDER BY started_at DESC
        LIMIT 1
        """
    )


async def record_message(
    conn: asyncpg.Connection,
    *,
    message: At0MailMessage,
    classification: MailClassification,
    status: str = "new",
) -> PersistedAt0Message:
    row = await conn.fetchrow(
        """
        INSERT INTO public.alpha_at0_mail_messages (
            mailbox, graph_message_id, internet_message_id, conversation_id,
            sender_name, sender_email, subject, received_at, body_preview,
            body_preview_sha256, web_link, classification, priority,
            status, classification_reason
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15
        )
        ON CONFLICT (mailbox, graph_message_id) DO NOTHING
        RETURNING id, status, classification
        """,
        message.mailbox,
        message.graph_message_id,
        message.internet_message_id,
        message.conversation_id,
        message.sender_name,
        message.sender_email,
        message.subject,
        message.received_at,
        message.body_preview,
        message.body_preview_sha256,
        message.web_link,
        classification.classification,
        classification.priority,
        status,
        classification.reason,
    )
    if row is not None:
        return PersistedAt0Message(
            id=str(row["id"]),
            created=True,
            status=row["status"],
            classification=row["classification"],
        )
    row = await conn.fetchrow(
        """
        SELECT id, status, classification
        FROM public.alpha_at0_mail_messages
        WHERE mailbox = $1 AND graph_message_id = $2
        """,
        message.mailbox,
        message.graph_message_id,
    )
    return PersistedAt0Message(
        id=str(row["id"]),
        created=False,
        status=row["status"],
        classification=row["classification"],
    )


async def record_draft_proposal(
    conn: asyncpg.Connection,
    *,
    message_id: str,
    mailbox: str,
    recipient_email: str | None,
    reply_subject: str,
    proposed_body: str,
) -> str:
    return str(
        await conn.fetchval(
            """
            INSERT INTO public.alpha_at0_mail_draft_proposals (
                mail_message_id, mailbox, recipient_email, reply_subject, proposed_body
            )
            VALUES ($1::uuid, $2, $3, $4, $5)
            RETURNING id
            """,
            message_id,
            mailbox,
            recipient_email,
            reply_subject,
            proposed_body,
        )
    )


async def dashboard_summary(conn: asyncpg.Connection) -> dict:
    rows = await conn.fetch(
        """
        SELECT mailbox, classification, status, priority, count(*)::int AS count
        FROM public.alpha_at0_mail_messages
        GROUP BY mailbox, classification, status, priority
        """
    )
    draft_rows = await conn.fetch(
        """
        SELECT status, count(*)::int AS count
        FROM public.alpha_at0_mail_draft_proposals
        GROUP BY status
        """
    )
    latest = await latest_scan_run(conn)
    return {
        "message_counts": [dict(row) for row in rows],
        "draft_counts": [dict(row) for row in draft_rows],
        "latest_scan": dict(latest) if latest else None,
    }
