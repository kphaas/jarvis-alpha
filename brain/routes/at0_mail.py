from __future__ import annotations

import os
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from brain.db.pool import get_pool
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.models.at0_mail import (
    At0MailDashboardOut,
    At0MailDraftProposalList,
    At0MailDraftProposalOut,
    At0MailDraftSendOut,
    At0MailDraftStatusUpdate,
    At0MailHealthOut,
    At0MailMailboxList,
    At0MailMessageList,
    At0MailMessageOut,
    At0MailScanResponse,
    At0SparkProfileOut,
)
from brain.services.at0_mail_agent import scan_at0_mail
from brain.services.at0_mail_graph_client import (
    At0MailConfigError,
    At0MailGraphError,
    configured_mailboxes,
    send_at0_mail_reply,
)
from brain.services.at0_mail_repository import dashboard_summary, health_summary
from brain.services.at0_mail_sender import (
    At0MailDraftNotFoundError,
    At0MailDraftNotReadyError,
    prepare_at0_mail_reply_send,
    record_at0_mail_reply_send_failure,
    record_at0_mail_reply_send_success,
)
from brain.services.at0_spark import at0_spark_profile

router = APIRouter(prefix="/v1/at0-mail", tags=["at0-mail"])


def _check_read_scope(request: Request) -> None:
    check_scopes(request, "at0_mail.read", "herald.read")


def _stale_after_minutes() -> int:
    try:
        return max(1, int(os.getenv("AT0_HERALD_STALE_AFTER_MINUTES", "180")))
    except ValueError:
        return 180


def _configured_mailboxes() -> tuple[str, ...]:
    return configured_mailboxes()


def _mailbox_or_400(mailbox: str | None) -> str | None:
    if mailbox is None:
        return None
    normalized = mailbox.strip().lower()
    if not normalized:
        return None
    if normalized not in _configured_mailboxes():
        raise HTTPException(status_code=400, detail="Mailbox is not configured")
    return normalized


@router.post("/scan", response_model=At0MailScanResponse)
async def scan_mailboxes(
    request: Request,
    _: str = Depends(require_auth),
    max_results: int = Query(default=25, ge=1, le=50),
    mailbox: str | None = None,
) -> At0MailScanResponse:
    check_scopes(request, "at0_mail.scan", "herald.write")
    normalized = _mailbox_or_400(mailbox)
    result = await scan_at0_mail(
        max_results=max_results,
        trigger="api",
        mailboxes=(normalized,) if normalized else None,
    )
    return At0MailScanResponse(**result.__dict__)


@router.get("/mailboxes", response_model=At0MailMailboxList)
async def get_mailboxes(
    request: Request,
    _: str = Depends(require_auth),
) -> At0MailMailboxList:
    _check_read_scope(request)
    return At0MailMailboxList(mailboxes=list(_configured_mailboxes()))


@router.get("/spark-profile", response_model=At0SparkProfileOut)
async def get_spark_profile(
    request: Request,
    _: str = Depends(require_auth),
) -> At0SparkProfileOut:
    _check_read_scope(request)
    return At0SparkProfileOut(**at0_spark_profile().to_payload())


@router.get("/dashboard", response_model=At0MailDashboardOut)
async def get_dashboard(
    request: Request,
    _: str = Depends(require_auth),
) -> At0MailDashboardOut:
    _check_read_scope(request)
    async with get_pool().acquire() as conn:
        summary = await dashboard_summary(conn)
    return At0MailDashboardOut(**summary)


@router.get("/health", response_model=At0MailHealthOut)
async def get_health(
    request: Request,
    _: str = Depends(require_auth),
) -> At0MailHealthOut:
    _check_read_scope(request)
    async with get_pool().acquire() as conn:
        summary = await health_summary(
            conn,
            stale_after_minutes=_stale_after_minutes(),
        )
    return At0MailHealthOut(**summary)


@router.get("/messages", response_model=At0MailMessageList)
async def list_messages(
    request: Request,
    _: str = Depends(require_auth),
    status: Literal[
        "new",
        "triaged",
        "drafted",
        "archived",
        "sent",
        "send_failed",
        "all",
    ] = Query(default="all"),
    classification: Literal[
        "lead",
        "support",
        "press",
        "partner",
        "investor",
        "vendor",
        "noise",
        "unknown",
        "all",
    ] = Query(default="all"),
    mailbox: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> At0MailMessageList:
    _check_read_scope(request)
    filters: list[str] = []
    params: list = []

    if status != "all":
        params.append(status)
        filters.append(f"status = ${len(params)}")
    if classification != "all":
        params.append(classification)
        filters.append(f"classification = ${len(params)}")
    normalized = _mailbox_or_400(mailbox)
    if normalized:
        params.append(normalized)
        filters.append(f"mailbox = ${len(params)}")

    where = " AND ".join(filters) if filters else "TRUE"
    params.append(limit)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, mailbox, graph_message_id, internet_message_id,
                   conversation_id, sender_name, sender_email, subject,
                   received_at, body_preview, web_link, classification,
                   priority, status, classification_reason, created_at
            FROM public.alpha_at0_mail_messages
            WHERE {where}
            ORDER BY received_at DESC NULLS LAST, created_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return At0MailMessageList(messages=[At0MailMessageOut(**dict(row)) for row in rows])


@router.get("/drafts", response_model=At0MailDraftProposalList)
async def list_drafts(
    request: Request,
    _: str = Depends(require_auth),
    status: Literal[
        "needs_review",
        "approved",
        "rejected",
        "sending",
        "sent",
        "send_failed",
        "all",
    ] = Query(default="needs_review"),
    mailbox: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> At0MailDraftProposalList:
    _check_read_scope(request)
    filters: list[str] = []
    params: list = []
    if status != "all":
        params.append(status)
        filters.append(f"d.status = ${len(params)}")
    normalized = _mailbox_or_400(mailbox)
    if normalized:
        params.append(normalized)
        filters.append(f"d.mailbox = ${len(params)}")
    where = " AND ".join(filters) if filters else "TRUE"
    params.append(limit)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT d.id, d.mail_message_id, d.mailbox, d.recipient_email,
                   d.reply_subject, d.proposed_body, d.status, d.reviewer_notes,
                   d.reviewed_by, d.reviewed_at, d.sent_at, d.send_failed_at,
                   d.send_error_type, d.send_error_message,
                   d.send_attempt_count, d.created_at,
                   m.sender_name, m.sender_email, m.subject AS original_subject,
                   m.received_at, m.classification, m.priority
            FROM public.alpha_at0_mail_draft_proposals d
            JOIN public.alpha_at0_mail_messages m
              ON m.id = d.mail_message_id
            WHERE {where}
            ORDER BY d.created_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return At0MailDraftProposalList(
        drafts=[At0MailDraftProposalOut(**dict(row)) for row in rows]
    )


@router.post("/drafts/{draft_id}/status", response_model=At0MailDraftProposalOut)
async def update_draft_status(
    draft_id: UUID,
    body: At0MailDraftStatusUpdate,
    request: Request,
    _: str = Depends(require_auth),
) -> At0MailDraftProposalOut:
    check_scopes(request, "at0_mail.write", "herald.write")
    reviewer = getattr(request.state, "sub", None) or getattr(
        request.state, "user_id", None
    )
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow(
                """
                SELECT status
                FROM public.alpha_at0_mail_draft_proposals
                WHERE id = $1
                FOR UPDATE
                """,
                draft_id,
            )
            if current is None:
                raise HTTPException(status_code=404, detail="Draft proposal not found")
            if current["status"] not in {"needs_review", "approved", "rejected"}:
                raise HTTPException(
                    status_code=409,
                    detail=f"Draft status is {current['status']}",
                )
            row = await conn.fetchrow(
                """
                UPDATE public.alpha_at0_mail_draft_proposals d
                SET status = $2,
                    reviewer_notes = $3,
                    reviewed_by = $4,
                    reviewed_at = now(),
                    updated_at = now()
                FROM public.alpha_at0_mail_messages m
                WHERE d.id = $1
                  AND m.id = d.mail_message_id
                RETURNING d.id, d.mail_message_id, d.mailbox, d.recipient_email,
                          d.reply_subject, d.proposed_body, d.status,
                          d.reviewer_notes, d.reviewed_by, d.reviewed_at,
                          d.sent_at, d.send_failed_at, d.send_error_type,
                          d.send_error_message, d.send_attempt_count,
                          d.created_at, m.sender_name, m.sender_email,
                          m.subject AS original_subject, m.received_at,
                          m.classification, m.priority
                """,
                draft_id,
                body.status,
                body.reviewer_notes,
                reviewer,
            )
    if row is None:
        raise HTTPException(status_code=404, detail="Draft proposal not found")
    return At0MailDraftProposalOut(**dict(row))


@router.post("/drafts/{draft_id}/send", response_model=At0MailDraftSendOut)
async def send_draft_reply(
    draft_id: UUID,
    request: Request,
    _: str = Depends(require_auth),
) -> At0MailDraftSendOut:
    check_scopes(request, "at0_mail.write", "herald.write")
    actor_sub = str(
        getattr(request.state, "sub", None)
        or getattr(request.state, "user_id", None)
        or "unknown"
    )
    actor_type = str(getattr(request.state, "actor_type", None) or "unknown")

    try:
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                prepared = await prepare_at0_mail_reply_send(
                    conn,
                    draft_id=draft_id,
                    actor_sub=actor_sub,
                    actor_type=actor_type,
                )
    except At0MailDraftNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Draft proposal not found") from exc
    except At0MailDraftNotReadyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        send_result = await send_at0_mail_reply(
            mailbox=prepared.mailbox,
            message_id=prepared.graph_message_id,
            reply_body=prepared.reply_body,
        )
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                await record_at0_mail_reply_send_failure(
                    conn,
                    prepared=prepared,
                    exc=exc,
                    status_code=status_code,
                )
        if isinstance(exc, At0MailConfigError):
            raise HTTPException(
                status_code=503,
                detail="AT-0 mail send is not configured",
            ) from exc
        if isinstance(exc, At0MailGraphError):
            raise HTTPException(
                status_code=502, detail="Microsoft Graph reply failed"
            ) from exc
        raise HTTPException(status_code=500, detail="AT-0 mail send failed") from exc

    async with get_pool().acquire() as conn:
        async with conn.transaction():
            recorded = await record_at0_mail_reply_send_success(
                conn,
                prepared=prepared,
                send_result=send_result,
            )

    return At0MailDraftSendOut(
        draft_id=recorded.draft_id,
        mail_message_id=recorded.mail_message_id,
        mailbox=recorded.mailbox,
        status="sent",
        graph_status_code=recorded.graph_status_code or 202,
        send_attempt_count=recorded.send_attempt_count,
        sent_at=recorded.sent_at,
    )
