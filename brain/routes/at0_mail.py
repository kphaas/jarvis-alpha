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
    At0MailDraftStatusUpdate,
    At0MailHealthOut,
    At0MailMessageList,
    At0MailMessageOut,
    At0MailScanResponse,
)
from brain.services.at0_mail_agent import scan_at0_mail
from brain.services.at0_mail_graph_client import configured_mailboxes
from brain.services.at0_mail_repository import dashboard_summary, health_summary

router = APIRouter(prefix="/v1/at0-mail", tags=["at0-mail"])


def _check_read_scope(request: Request) -> None:
    check_scopes(request, "at0_mail.read", "herald.read")


def _stale_after_minutes() -> int:
    try:
        return max(1, int(os.getenv("AT0_HERALD_STALE_AFTER_MINUTES", "180")))
    except ValueError:
        return 180


@router.post("/scan", response_model=At0MailScanResponse)
async def scan_mailboxes(
    request: Request,
    _: str = Depends(require_auth),
    max_results: int = Query(default=25, ge=1, le=50),
) -> At0MailScanResponse:
    check_scopes(request, "at0_mail.scan", "herald.write")
    result = await scan_at0_mail(max_results=max_results, trigger="api")
    return At0MailScanResponse(**result.__dict__)


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
    status: Literal["new", "triaged", "drafted", "archived", "all"] = Query(
        default="all"
    ),
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
    if mailbox:
        normalized = mailbox.lower()
        if normalized not in configured_mailboxes():
            raise HTTPException(status_code=400, detail="Mailbox is not configured")
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
    status: Literal["needs_review", "approved", "rejected", "all"] = Query(
        default="needs_review"
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> At0MailDraftProposalList:
    _check_read_scope(request)
    filters: list[str] = []
    params: list = []
    if status != "all":
        params.append(status)
        filters.append(f"d.status = ${len(params)}")
    where = " AND ".join(filters) if filters else "TRUE"
    params.append(limit)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT d.id, d.mail_message_id, d.mailbox, d.recipient_email,
                   d.reply_subject, d.proposed_body, d.status, d.reviewer_notes,
                   d.reviewed_by, d.reviewed_at, d.created_at,
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
