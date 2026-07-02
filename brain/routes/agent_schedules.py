"""Governed scheduled work for Alpha Agent Board."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from brain.db.rls import rls_connection
from brain.middleware.scopes import check_scopes
from brain.routes.agent_board import (
    SourceSurface,
    WorkItemRole,
    _assignment_warnings,
    _load_agent,
    _load_skill_policies,
    highest_approval_tier,
    normalize_required_skills,
)
from brain.services.agent_schedules import (
    materialize_due_scheduled_work,
    parse_schedule_text,
)
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

router = APIRouter(prefix="/v1/agent-schedules", tags=["agent-schedules"])

ScheduleStatus = Literal["active", "paused", "cancelled", "completed"]


class ScheduledWorkOut(BaseModel):
    id: str
    workspace_id: str
    title: str
    description: str
    schedule_text: str
    schedule_kind: str
    day_of_week: int | None = None
    time_of_day: str
    timezone: str
    status: ScheduleStatus
    source_surface: str
    role: str
    priority: int
    assigned_agent_id: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    approval_tier: str
    next_run_at: str | None = None
    last_run_at: str | None = None
    last_work_item_id: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_by: str
    created_at: str
    updated_at: str


class CreateScheduledWorkRequest(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=4000)
    schedule_text: str = Field(min_length=1, max_length=300)
    source_surface: SourceSurface = "system"
    role: WorkItemRole = "general"
    priority: int = Field(default=5, ge=1, le=10)
    assigned_agent_id: str | None = Field(default=None, max_length=64)
    required_skills: list[str] = Field(default_factory=list, max_length=20)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=20)
    timezone: str = Field(default="America/New_York", max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title", "schedule_text")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must be non-empty")
        return stripped

    @field_validator("required_skills")
    @classmethod
    def validate_required_skills(cls, value: list[str]) -> list[str]:
        return normalize_required_skills(value)

    @field_validator("acceptance_criteria")
    @classmethod
    def strip_acceptance_criteria(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class UpdateScheduledWorkStatusRequest(BaseModel):
    status: Literal["active", "paused", "cancelled"]


class MaterializeDueResponse(BaseModel):
    count: int
    items: list[dict[str, str | None]]


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _jsonb_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return dict(value)


def _jsonb_list(value: Any) -> list[str]:
    if value is None:
        return []
    parsed = json.loads(value) if isinstance(value, str) else value
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _scheduled_work_from_row(row: Any) -> ScheduledWorkOut:
    return ScheduledWorkOut(
        id=str(row["id"]),
        workspace_id=row["workspace_id"],
        title=row["title"],
        description=row["description"],
        schedule_text=row["schedule_text"],
        schedule_kind=row["schedule_kind"],
        day_of_week=row["day_of_week"],
        time_of_day=str(row["time_of_day"]),
        timezone=row["timezone"],
        status=row["status"],
        source_surface=row["source_surface"],
        role=row["role"],
        priority=row["priority"],
        assigned_agent_id=row["assigned_agent_id"],
        required_skills=list(row["required_skills"] or []),
        approval_tier=row["approval_tier"],
        next_run_at=_iso(row["next_run_at"]),
        last_run_at=_iso(row["last_run_at"]),
        last_work_item_id=str(row["last_work_item_id"])
        if row["last_work_item_id"]
        else None,
        acceptance_criteria=_jsonb_list(row["acceptance_criteria"]),
        metadata=_jsonb_dict(row["metadata"]),
        created_by=row["created_by"],
        created_at=_iso(row["created_at"]) or "",
        updated_at=_iso(row["updated_at"]) or "",
    )


@router.get("", response_model=list[ScheduledWorkOut])
async def list_scheduled_work(
    request: Request,
    status: ScheduleStatus | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ScheduledWorkOut]:
    check_scopes(request, "agents.read", "agent_board.read")
    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            """
            SELECT id, workspace_id, title, description, schedule_text,
                   schedule_kind, day_of_week, time_of_day, timezone, status,
                   source_surface, role, priority, assigned_agent_id,
                   required_skills, approval_tier, next_run_at, last_run_at,
                   last_work_item_id, acceptance_criteria, metadata, created_by,
                   created_at, updated_at
              FROM public.alpha_agent_scheduled_work
             WHERE ($1::text IS NULL OR status = $1)
             ORDER BY next_run_at ASC NULLS LAST, created_at DESC
             LIMIT $2
            """,
            status,
            limit,
        )
    return [_scheduled_work_from_row(row) for row in rows]


@router.post("", response_model=ScheduledWorkOut)
async def create_scheduled_work(
    request: Request,
    body: CreateScheduledWorkRequest,
) -> ScheduledWorkOut:
    check_scopes(request, "agents.write", "agent_board.write")
    actor = str(getattr(request.state, "user_id", "unknown"))
    workspace_id = str(getattr(request.state, "workspace_id", "") or "default")
    try:
        parsed = parse_schedule_text(
            body.schedule_text,
            now=datetime.now(UTC),
            timezone_name=body.timezone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async with rls_connection(request) as conn:
        skills_by_name = await _load_skill_policies(conn, body.required_skills)
        assigned_agent = await _load_agent(conn, body.assigned_agent_id)
        skills = [skills_by_name[name] for name in body.required_skills]
        approval_tier = highest_approval_tier(skills)
        metadata = dict(body.metadata)
        warnings = _assignment_warnings(
            assigned_agent,
            body.required_skills,
            approval_tier,
        )
        if warnings:
            metadata["assignment_warnings"] = warnings

        row = await conn.fetchrow(
            """
            INSERT INTO public.alpha_agent_scheduled_work (
                workspace_id, title, description, schedule_text, schedule_kind,
                day_of_week, time_of_day, timezone, source_surface, role,
                priority, assigned_agent_id, required_skills, approval_tier,
                next_run_at, acceptance_criteria, metadata, created_by
            )
            VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9, $10,
                $11, $12, $13::text[], $14,
                $15, $16::jsonb, $17::jsonb, $18
            )
            RETURNING id, workspace_id, title, description, schedule_text,
                      schedule_kind, day_of_week, time_of_day, timezone, status,
                      source_surface, role, priority, assigned_agent_id,
                      required_skills, approval_tier, next_run_at, last_run_at,
                      last_work_item_id, acceptance_criteria, metadata, created_by,
                      created_at, updated_at
            """,
            workspace_id,
            body.title,
            body.description,
            body.schedule_text,
            parsed.schedule_kind,
            parsed.day_of_week,
            parsed.time_of_day,
            parsed.timezone,
            body.source_surface,
            body.role,
            body.priority,
            body.assigned_agent_id,
            body.required_skills,
            approval_tier,
            parsed.next_run_at,
            json.dumps(body.acceptance_criteria),
            json.dumps(metadata),
            actor,
        )
        if row is None:
            raise HTTPException(status_code=500, detail="scheduled work insert failed")

    logger.info(
        "AGENT_SCHEDULE_CREATED schedule_id=%s next_run_at=%s approval_tier=%s",
        row["id"],
        row["next_run_at"],
        approval_tier,
    )
    return _scheduled_work_from_row(row)


@router.patch("/{schedule_id}/status", response_model=ScheduledWorkOut)
async def update_scheduled_work_status(
    schedule_id: UUID,
    request: Request,
    body: UpdateScheduledWorkStatusRequest,
) -> ScheduledWorkOut:
    check_scopes(request, "agents.write", "agent_board.write")
    async with rls_connection(request) as conn:
        row = await conn.fetchrow(
            """
            UPDATE public.alpha_agent_scheduled_work
               SET status = $2
             WHERE id = $1
               AND status != 'completed'
             RETURNING id, workspace_id, title, description, schedule_text,
                       schedule_kind, day_of_week, time_of_day, timezone, status,
                       source_surface, role, priority, assigned_agent_id,
                       required_skills, approval_tier, next_run_at, last_run_at,
                       last_work_item_id, acceptance_criteria, metadata, created_by,
                       created_at, updated_at
            """,
            schedule_id,
            body.status,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Scheduled work not found")
    return _scheduled_work_from_row(row)


@router.post("/materialize-due", response_model=MaterializeDueResponse)
async def materialize_due_schedules(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
) -> MaterializeDueResponse:
    check_scopes(request, "agents.write", "agent_board.write")
    actor = str(getattr(request.state, "user_id", "unknown"))
    async with rls_connection(request) as conn:
        items = await materialize_due_scheduled_work(
            conn,
            now=datetime.now(UTC),
            limit=limit,
            actor=actor,
        )
    return MaterializeDueResponse(
        count=len(items),
        items=[
            {
                "schedule_id": item.schedule_id,
                "work_item_id": item.work_item_id,
                "next_run_at": item.next_run_at,
                "schedule_status": item.schedule_status,
            }
            for item in items
        ],
    )
