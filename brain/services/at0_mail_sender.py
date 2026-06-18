from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import asyncpg

from brain.services.at0_mail_graph_client import At0MailSendResult


class At0MailDraftSendError(RuntimeError):
    pass


class At0MailDraftNotFoundError(At0MailDraftSendError):
    pass


class At0MailDraftNotReadyError(At0MailDraftSendError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedAt0MailReplySend:
    draft_id: UUID
    mail_message_id: UUID
    mailbox: str
    graph_message_id: str
    reply_body: str
    actor_sub: str
    actor_type: str
    send_attempt_count: int


@dataclass(frozen=True, slots=True)
class At0MailRecordedSend:
    draft_id: UUID
    mail_message_id: UUID
    mailbox: str
    status: str
    graph_status_code: int | None
    send_attempt_count: int
    sent_at: datetime | None


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).replace("\n", " ").strip()
    return message[:240] or exc.__class__.__name__


def _actor(value: str | None, fallback: str) -> str:
    clean = (value or fallback).strip()
    if not clean:
        clean = fallback
    return clean[:160]


def _body_hash(reply_body: str) -> str:
    digest = hashlib.sha256(reply_body.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


async def prepare_at0_mail_reply_send(
    conn: asyncpg.Connection,
    *,
    draft_id: UUID,
    actor_sub: str | None,
    actor_type: str | None,
) -> PreparedAt0MailReplySend:
    row = await conn.fetchrow(
        """
        SELECT d.id, d.mail_message_id, d.mailbox, d.proposed_body,
               d.status, d.send_attempt_count, m.graph_message_id
        FROM public.alpha_at0_mail_draft_proposals d
        JOIN public.alpha_at0_mail_messages m
          ON m.id = d.mail_message_id
        WHERE d.id = $1
        FOR UPDATE OF d
        """,
        draft_id,
    )
    if row is None:
        raise At0MailDraftNotFoundError("draft_not_found")
    if row["status"] not in {"approved", "send_failed"}:
        raise At0MailDraftNotReadyError(f"draft_status_{row['status']}")

    updated = await conn.fetchrow(
        """
        UPDATE public.alpha_at0_mail_draft_proposals
        SET status = 'sending',
            send_attempt_count = send_attempt_count + 1,
            last_send_attempt_at = now(),
            send_failed_at = NULL,
            send_error_type = NULL,
            send_error_message = NULL,
            updated_at = now()
        WHERE id = $1
        RETURNING send_attempt_count
        """,
        draft_id,
    )
    attempt = int(updated["send_attempt_count"])
    actor_sub_clean = _actor(actor_sub, "unknown")
    actor_type_clean = _actor(actor_type, "unknown")
    prepared = PreparedAt0MailReplySend(
        draft_id=row["id"],
        mail_message_id=row["mail_message_id"],
        mailbox=row["mailbox"],
        graph_message_id=row["graph_message_id"],
        reply_body=row["proposed_body"],
        actor_sub=actor_sub_clean,
        actor_type=actor_type_clean,
        send_attempt_count=attempt,
    )
    await _append_send_event(
        conn,
        prepared=prepared,
        event_type="sending",
        http_status_code=None,
        error_type=None,
        error_message=None,
        event_payload={
            "provider_operation": "message.reply",
            "send_attempt_count": attempt,
            "reply_body_hash": _body_hash(prepared.reply_body),
        },
    )
    return prepared


async def record_at0_mail_reply_send_success(
    conn: asyncpg.Connection,
    *,
    prepared: PreparedAt0MailReplySend,
    send_result: At0MailSendResult,
) -> At0MailRecordedSend:
    row = await conn.fetchrow(
        """
        UPDATE public.alpha_at0_mail_draft_proposals
        SET status = 'sent',
            sent_at = now(),
            send_failed_at = NULL,
            send_error_type = NULL,
            send_error_message = NULL,
            updated_at = now()
        WHERE id = $1
        RETURNING sent_at
        """,
        prepared.draft_id,
    )
    await conn.execute(
        """
        UPDATE public.alpha_at0_mail_messages
        SET status = 'sent',
            updated_at = now()
        WHERE id = $1
        """,
        prepared.mail_message_id,
    )
    await _append_send_event(
        conn,
        prepared=prepared,
        event_type="sent",
        http_status_code=send_result.status_code,
        error_type=None,
        error_message=None,
        event_payload={
            "provider_operation": send_result.provider_operation,
            "send_attempt_count": prepared.send_attempt_count,
        },
    )
    return At0MailRecordedSend(
        draft_id=prepared.draft_id,
        mail_message_id=prepared.mail_message_id,
        mailbox=prepared.mailbox,
        status="sent",
        graph_status_code=send_result.status_code,
        send_attempt_count=prepared.send_attempt_count,
        sent_at=row["sent_at"],
    )


async def record_at0_mail_reply_send_failure(
    conn: asyncpg.Connection,
    *,
    prepared: PreparedAt0MailReplySend,
    exc: Exception,
    status_code: int | None,
) -> At0MailRecordedSend:
    error_message = _safe_error_message(exc)
    error_type = exc.__class__.__name__
    await conn.execute(
        """
        UPDATE public.alpha_at0_mail_draft_proposals
        SET status = 'send_failed',
            send_failed_at = now(),
            send_error_type = $2,
            send_error_message = $3,
            updated_at = now()
        WHERE id = $1
        """,
        prepared.draft_id,
        error_type,
        error_message,
    )
    await conn.execute(
        """
        UPDATE public.alpha_at0_mail_messages
        SET status = 'send_failed',
            updated_at = now()
        WHERE id = $1
        """,
        prepared.mail_message_id,
    )
    await _append_send_event(
        conn,
        prepared=prepared,
        event_type="send_failed",
        http_status_code=status_code,
        error_type=error_type,
        error_message=error_message,
        event_payload={
            "provider_operation": "message.reply",
            "send_attempt_count": prepared.send_attempt_count,
        },
    )
    return At0MailRecordedSend(
        draft_id=prepared.draft_id,
        mail_message_id=prepared.mail_message_id,
        mailbox=prepared.mailbox,
        status="send_failed",
        graph_status_code=status_code,
        send_attempt_count=prepared.send_attempt_count,
        sent_at=None,
    )


async def _append_send_event(
    conn: asyncpg.Connection,
    *,
    prepared: PreparedAt0MailReplySend,
    event_type: str,
    http_status_code: int | None,
    error_type: str | None,
    error_message: str | None,
    event_payload: dict[str, object],
) -> None:
    await conn.execute(
        """
        INSERT INTO public.alpha_at0_mail_send_events (
            draft_proposal_id, mail_message_id, mailbox, graph_message_id,
            event_type, actor_sub, actor_type, http_status_code,
            error_type, error_message, event_payload
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
        """,
        prepared.draft_id,
        prepared.mail_message_id,
        prepared.mailbox,
        prepared.graph_message_id,
        event_type,
        prepared.actor_sub,
        prepared.actor_type,
        http_status_code,
        error_type,
        error_message,
        json.dumps(event_payload, sort_keys=True),
    )
