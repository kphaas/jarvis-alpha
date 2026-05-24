from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from brain.db.pool import get_pool
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.models.school_email import (
    CandidateStatusUpdate,
    SchoolEmailScanResponse,
    SchoolEventCandidateList,
    SchoolEventCandidateOut,
)
from brain.services.school_email_agent import scan_school_email

router = APIRouter(prefix="/v1/school-email", tags=["school-email"])


def _check_school_scope(request: Request) -> None:
    check_scopes(request, "school_email.read", "school_email.write")


def _candidate_from_row(row) -> SchoolEventCandidateOut:
    event_time = row["event_time"]
    return SchoolEventCandidateOut(
        id=row["id"],
        gmail_message_id=row["gmail_message_id"],
        source=row["source"],
        school_name=row["school_name"],
        title=row["title"],
        event_date=row["event_date"],
        event_time=event_time,
        end_time=row["end_time"],
        location=row["location"],
        notes=row["notes"],
        confidence=float(row["confidence"]),
        status=row["status"],
        family_external_id=row["family_external_id"],
        family_event_id=row["family_event_id"],
        sender=row["sender"],
        subject=row["subject"],
        received_at=row["received_at"],
        created_at=row["created_at"],
        family_import={
            "title": row["title"],
            "event_date": row["event_date"].isoformat(),
            "event_time": event_time.isoformat(timespec="minutes")
            if event_time
            else None,
            "category": "school",
            "notes": row["notes"],
            "location": row["location"],
            "source": "alpha_school_email",
            "external_id": row["family_external_id"],
            "source_metadata": {
                "alpha_candidate_id": str(row["id"]),
                "gmail_message_id": row["gmail_message_id"],
                "school_name": row["school_name"],
                "confidence": float(row["confidence"]),
            },
        },
    )


@router.post("/scan", response_model=SchoolEmailScanResponse)
async def scan_school_emails(
    request: Request,
    _: str = Depends(require_auth),
    query: str | None = None,
    max_results: int = Query(default=25, ge=1, le=100),
) -> SchoolEmailScanResponse:
    check_scopes(request, "school_email.scan", "school_email.write")
    result = await scan_school_email(query=query, max_results=max_results)
    return SchoolEmailScanResponse(**result.__dict__)


@router.get("/candidates", response_model=SchoolEventCandidateList)
async def list_school_event_candidates(
    request: Request,
    _: str = Depends(require_auth),
    status: Literal["needs_review", "approved", "imported", "ignored", "all"] = Query(
        default="needs_review"
    ),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> SchoolEventCandidateList:
    _check_school_scope(request)
    filters: list[str] = []
    params: list = []

    if status != "all":
        params.append(status)
        filters.append(f"c.status = ${len(params)}")
    if date_from:
        params.append(date_from)
        filters.append(f"c.event_date >= ${len(params)}")
    if date_to:
        params.append(date_to)
        filters.append(f"c.event_date <= ${len(params)}")

    where = " AND ".join(filters) if filters else "TRUE"
    params.append(limit)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT c.id, c.gmail_message_id, c.source, c.school_name, c.title,
                   c.event_date, c.event_time, c.end_time, c.location, c.notes,
                   c.confidence, c.status, c.family_external_id, c.family_event_id,
                   c.created_at, m.sender, m.subject, m.received_at
            FROM public.alpha_school_event_candidates c
            JOIN public.alpha_school_email_messages m
              ON m.id = c.email_message_id
            WHERE {where}
            ORDER BY c.event_date ASC, c.event_time ASC NULLS LAST, c.created_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return SchoolEventCandidateList(
        candidates=[_candidate_from_row(row) for row in rows]
    )


@router.post(
    "/candidates/{candidate_id}/status", response_model=SchoolEventCandidateOut
)
async def update_school_event_candidate_status(
    candidate_id: UUID,
    body: CandidateStatusUpdate,
    request: Request,
    _: str = Depends(require_auth),
) -> SchoolEventCandidateOut:
    check_scopes(request, "school_email.write")
    reviewer = getattr(request.state, "sub", None) or getattr(
        request.state, "user_id", None
    )
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE public.alpha_school_event_candidates c
            SET status = $2,
                family_event_id = COALESCE($3, family_event_id),
                reviewed_by = $4,
                reviewed_at = now(),
                updated_at = now()
            FROM public.alpha_school_email_messages m
            WHERE c.id = $1
              AND m.id = c.email_message_id
            RETURNING c.id, c.gmail_message_id, c.source, c.school_name, c.title,
                      c.event_date, c.event_time, c.end_time, c.location, c.notes,
                      c.confidence, c.status, c.family_external_id, c.family_event_id,
                      c.created_at, m.sender, m.subject, m.received_at
            """,
            candidate_id,
            body.status,
            body.family_event_id,
            reviewer,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return _candidate_from_row(row)
