"""Alpha Agent Board and governed work queue API."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from brain.db.rls import rls_connection
from brain.middleware.scopes import check_scopes
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

router = APIRouter(prefix="/v1/agent-board", tags=["agent-board"])

WorkItemRole = Literal["general", "research", "code", "review", "deploy", "monitor"]
WorkItemStatus = Literal[
    "queued",
    "in_progress",
    "blocked",
    "needs_approval",
    "handoff_ready",
    "done",
    "cancelled",
]
SourceSurface = Literal[
    "helm_companion", "helm_ask", "alpha", "chatops", "manual", "system"
]
RegistryStatusFilter = Literal["planned", "active", "disabled", "all"]

_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_TIER_RANK = {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "T5": 5}


class SkillPolicyOut(BaseModel):
    name: str
    domain: str
    action: str
    description: str
    approval_tier: str
    scope: str
    status: str
    mutates_state: bool
    body_access: bool
    idempotency_required: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentBoardAgentOut(BaseModel):
    agent_id: str
    display_name: str
    purpose: str
    risk_tier: str
    status: str
    enabled: bool
    allowed_skills: list[str] = Field(default_factory=list)
    allowed_scopes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkItemOut(BaseModel):
    id: str
    workspace_id: str
    title: str
    description: str
    source_surface: str
    requested_by: str
    role: WorkItemRole
    status: WorkItemStatus
    priority: int
    assigned_agent_id: str | None = None
    assigned_agent_display_name: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    skills: list[SkillPolicyOut] = Field(default_factory=list)
    approval_tier: str
    approval_required: bool
    approval_queue_id: str | None = None
    task_graph_id: str | None = None
    due_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    blocked_reason: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    handoff: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    assignment_warnings: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class BoardColumnOut(BaseModel):
    status: WorkItemStatus
    count: int
    items: list[WorkItemOut]


class AgentBoardOut(BaseModel):
    count: int
    columns: list[BoardColumnOut]


class AgentBoardRegistryOut(BaseModel):
    skill_count: int
    agent_count: int
    skills: list[SkillPolicyOut]
    agents: list[AgentBoardAgentOut]


class CreateWorkItemRequest(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=4000)
    source_surface: SourceSurface = "helm_companion"
    role: WorkItemRole = "general"
    priority: int = Field(default=5, ge=1, le=10)
    assigned_agent_id: str | None = Field(default=None, max_length=64)
    required_skills: list[str] = Field(default_factory=list, max_length=20)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=20)
    due_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("title must be non-empty")
        return title

    @field_validator("required_skills")
    @classmethod
    def validate_required_skills(cls, value: list[str]) -> list[str]:
        return normalize_required_skills(value)

    @field_validator("acceptance_criteria")
    @classmethod
    def strip_acceptance_criteria(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class UpdateWorkItemStatusRequest(BaseModel):
    status: WorkItemStatus
    blocked_reason: str | None = Field(default=None, max_length=1000)
    handoff: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


def normalize_required_skills(value: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_name in value:
        skill_name = raw_name.strip()
        if not _SKILL_NAME_RE.match(skill_name):
            raise ValueError(f"invalid skill name: {raw_name}")
        if skill_name not in seen:
            normalized.append(skill_name)
            seen.add(skill_name)
    return normalized


def highest_approval_tier(skills: list[SkillPolicyOut]) -> str:
    highest = "T1"
    for skill in skills:
        if _TIER_RANK[skill.approval_tier] > _TIER_RANK[highest]:
            highest = skill.approval_tier
    return highest


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
    if isinstance(value, str):
        parsed = json.loads(value)
    else:
        parsed = value
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _skills_from_rows(rows: list[Any]) -> dict[str, SkillPolicyOut]:
    skills: dict[str, SkillPolicyOut] = {}
    for row in rows:
        skill = SkillPolicyOut(
            name=row["skill_name"],
            domain=row["domain"],
            action=row["action"],
            description=row["description"],
            approval_tier=row["approval_tier"],
            scope=row["scope"],
            status=row["status"],
            mutates_state=row["mutates_state"],
            body_access=row["body_access"],
            idempotency_required=row["idempotency_required"],
            metadata=_jsonb_dict(row["metadata"]),
        )
        skills[skill.name] = skill
    return skills


def _agent_from_row(row: Any) -> AgentBoardAgentOut:
    return AgentBoardAgentOut(
        agent_id=row["agent_id"],
        display_name=row["display_name"],
        purpose=row["purpose"],
        risk_tier=row["risk_tier"],
        status=row["status"],
        enabled=row["enabled"],
        allowed_skills=list(row["allowed_skills"] or []),
        allowed_scopes=list(row["allowed_scopes"] or []),
        metadata=_jsonb_dict(row["metadata"]),
    )


def _assignment_warnings(
    assigned_agent: AgentBoardAgentOut | None,
    required_skills: list[str],
    approval_tier: str,
) -> list[str]:
    if assigned_agent is None:
        return []
    warnings: list[str] = []
    allowed_skills = set(assigned_agent.allowed_skills)
    missing = [skill for skill in required_skills if skill not in allowed_skills]
    if missing:
        warnings.append(
            "assigned agent is missing required skills: " + ", ".join(missing)
        )
    if _TIER_RANK[approval_tier] > _TIER_RANK[assigned_agent.risk_tier]:
        warnings.append(
            f"work item approval tier {approval_tier} exceeds agent risk tier {assigned_agent.risk_tier}"
        )
    if not assigned_agent.enabled:
        warnings.append("assigned agent is disabled")
    return warnings


def _work_item_from_row(
    row: Any,
    skills_by_name: dict[str, SkillPolicyOut],
) -> WorkItemOut:
    required_skills = list(row["required_skills"] or [])
    metadata = _jsonb_dict(row["metadata"])
    skills = [
        skills_by_name[name] for name in required_skills if name in skills_by_name
    ]
    return WorkItemOut(
        id=str(row["id"]),
        workspace_id=row["workspace_id"],
        title=row["title"],
        description=row["description"],
        source_surface=row["source_surface"],
        requested_by=row["requested_by"],
        role=row["role"],
        status=row["status"],
        priority=row["priority"],
        assigned_agent_id=row["assigned_agent_id"],
        assigned_agent_display_name=row.get("assigned_agent_display_name")
        if hasattr(row, "get")
        else row["assigned_agent_display_name"],
        required_skills=required_skills,
        skills=skills,
        approval_tier=row["approval_tier"],
        approval_required=_TIER_RANK[row["approval_tier"]] >= _TIER_RANK["T4"],
        approval_queue_id=str(row["approval_queue_id"])
        if row["approval_queue_id"]
        else None,
        task_graph_id=str(row["task_graph_id"]) if row["task_graph_id"] else None,
        due_at=_iso(row["due_at"]),
        started_at=_iso(row["started_at"]),
        completed_at=_iso(row["completed_at"]),
        blocked_reason=row["blocked_reason"],
        acceptance_criteria=_jsonb_list(row["acceptance_criteria"]),
        handoff=_jsonb_dict(row["handoff"]),
        metadata=metadata,
        assignment_warnings=list(metadata.get("assignment_warnings", [])),
        created_at=_iso(row["created_at"]) or "",
        updated_at=_iso(row["updated_at"]) or "",
    )


async def _load_skill_policies(
    conn: Any, skill_names: list[str]
) -> dict[str, SkillPolicyOut]:
    if not skill_names:
        return {}
    rows = await conn.fetch(
        """
        SELECT skill_name, domain, action, description, approval_tier, scope,
               status, mutates_state, body_access, idempotency_required, metadata
          FROM public.alpha_skill_registry
         WHERE skill_name = ANY($1::text[])
        """,
        skill_names,
    )
    skills_by_name = _skills_from_rows(rows)
    missing = [name for name in skill_names if name not in skills_by_name]
    if missing:
        raise HTTPException(
            status_code=400,
            detail={"error": "unknown_skills", "skills": missing},
        )
    disabled = [
        name for name in skill_names if skills_by_name[name].status == "disabled"
    ]
    if disabled:
        raise HTTPException(
            status_code=409,
            detail={"error": "disabled_skills", "skills": disabled},
        )
    return skills_by_name


async def _load_agent(conn: Any, agent_id: str | None) -> AgentBoardAgentOut | None:
    if agent_id is None:
        return None
    row = await conn.fetchrow(
        """
        SELECT agent_id, display_name, purpose, risk_tier, status, enabled,
               allowed_skills, allowed_scopes, metadata
          FROM public.alpha_agents
         WHERE agent_id = $1
        """,
        agent_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_from_row(row)


async def _load_referenced_skills(
    conn: Any,
    rows: list[Any],
) -> dict[str, SkillPolicyOut]:
    skill_names = sorted(
        {skill for row in rows for skill in list(row["required_skills"] or [])}
    )
    if not skill_names:
        return {}
    skill_rows = await conn.fetch(
        """
        SELECT skill_name, domain, action, description, approval_tier, scope,
               status, mutates_state, body_access, idempotency_required, metadata
          FROM public.alpha_skill_registry
         WHERE skill_name = ANY($1::text[])
        """,
        skill_names,
    )
    return _skills_from_rows(skill_rows)


@router.get("", response_model=AgentBoardOut)
async def get_agent_board(
    request: Request,
    status: WorkItemStatus | None = Query(default=None),
    role: WorkItemRole | None = Query(default=None),
    assigned_agent_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> AgentBoardOut:
    check_scopes(request, "agents.read", "agent_board.read")
    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            """
            SELECT wi.id, wi.workspace_id, wi.title, wi.description,
                   wi.source_surface, wi.requested_by, wi.role, wi.status,
                   wi.priority, wi.assigned_agent_id,
                   a.display_name AS assigned_agent_display_name,
                   wi.required_skills, wi.approval_tier, wi.approval_queue_id,
                   wi.task_graph_id, wi.due_at, wi.started_at, wi.completed_at,
                   wi.blocked_reason, wi.acceptance_criteria, wi.handoff,
                   wi.metadata, wi.created_at, wi.updated_at
              FROM public.alpha_agent_work_items wi
              LEFT JOIN public.alpha_agents a
                ON a.agent_id = wi.assigned_agent_id
             WHERE ($1::text IS NULL OR wi.status = $1)
               AND ($2::text IS NULL OR wi.role = $2)
               AND ($3::text IS NULL OR wi.assigned_agent_id = $3)
             ORDER BY
               CASE wi.status
                 WHEN 'needs_approval' THEN 1
                 WHEN 'blocked' THEN 2
                 WHEN 'in_progress' THEN 3
                 WHEN 'handoff_ready' THEN 4
                 WHEN 'queued' THEN 5
                 WHEN 'done' THEN 6
                 ELSE 7
               END,
               wi.priority DESC,
               wi.created_at DESC
             LIMIT $4
            """,
            status,
            role,
            assigned_agent_id,
            limit,
        )
        skills_by_name = await _load_referenced_skills(conn, rows)

    items = [_work_item_from_row(row, skills_by_name) for row in rows]
    columns: list[BoardColumnOut] = []
    for column_status in WorkItemStatus.__args__:  # type: ignore[attr-defined]
        column_items = [item for item in items if item.status == column_status]
        columns.append(
            BoardColumnOut(
                status=column_status,
                count=len(column_items),
                items=column_items,
            )
        )
    return AgentBoardOut(count=len(items), columns=columns)


@router.get("/registry", response_model=AgentBoardRegistryOut)
async def get_agent_board_registry(
    request: Request,
    domain: str | None = Query(default=None),
    status: RegistryStatusFilter = Query(default="all"),
) -> AgentBoardRegistryOut:
    check_scopes(request, "agents.read", "skills.read", "agent_board.read")
    filters: list[str] = []
    params: list[Any] = []
    if domain:
        params.append(domain)
        filters.append(f"domain = ${len(params)}")
    if status != "all":
        params.append(status)
        filters.append(f"status = ${len(params)}")
    where = " AND ".join(filters) if filters else "TRUE"

    async with rls_connection(request) as conn:
        skill_rows = await conn.fetch(
            f"""
            SELECT skill_name, domain, action, description, approval_tier, scope,
                   status, mutates_state, body_access, idempotency_required, metadata
              FROM public.alpha_skill_registry
             WHERE {where}
             ORDER BY domain ASC, skill_name ASC
            """,
            *params,
        )
        agent_rows = await conn.fetch(
            """
            SELECT agent_id, display_name, purpose, risk_tier, status, enabled,
                   allowed_skills, allowed_scopes, metadata
              FROM public.alpha_agents
             ORDER BY enabled DESC, status ASC, agent_id ASC
            """,
        )

    skills = list(_skills_from_rows(skill_rows).values())
    agents = [_agent_from_row(row) for row in agent_rows]
    return AgentBoardRegistryOut(
        skill_count=len(skills),
        agent_count=len(agents),
        skills=skills,
        agents=agents,
    )


@router.get("/work-items/{work_item_id}", response_model=WorkItemOut)
async def get_work_item(work_item_id: UUID, request: Request) -> WorkItemOut:
    check_scopes(request, "agents.read", "agent_board.read")
    async with rls_connection(request) as conn:
        row = await conn.fetchrow(
            """
            SELECT wi.id, wi.workspace_id, wi.title, wi.description,
                   wi.source_surface, wi.requested_by, wi.role, wi.status,
                   wi.priority, wi.assigned_agent_id,
                   a.display_name AS assigned_agent_display_name,
                   wi.required_skills, wi.approval_tier, wi.approval_queue_id,
                   wi.task_graph_id, wi.due_at, wi.started_at, wi.completed_at,
                   wi.blocked_reason, wi.acceptance_criteria, wi.handoff,
                   wi.metadata, wi.created_at, wi.updated_at
              FROM public.alpha_agent_work_items wi
              LEFT JOIN public.alpha_agents a
                ON a.agent_id = wi.assigned_agent_id
             WHERE wi.id = $1
            """,
            work_item_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Work item not found")
        skills_by_name = await _load_referenced_skills(conn, [row])
    return _work_item_from_row(row, skills_by_name)


@router.post("/work-items", response_model=WorkItemOut)
async def create_work_item(
    request: Request,
    body: CreateWorkItemRequest,
) -> WorkItemOut:
    check_scopes(request, "agents.write", "agent_board.write")
    actor = str(getattr(request.state, "user_id", "unknown"))
    workspace_id = str(getattr(request.state, "workspace_id", "") or "default")

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
            INSERT INTO public.alpha_agent_work_items (
                workspace_id, title, description, source_surface, requested_by,
                role, priority, assigned_agent_id, required_skills,
                approval_tier, due_at, acceptance_criteria, metadata
            )
            VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9::text[],
                $10, $11, $12::jsonb, $13::jsonb
            )
            RETURNING id, workspace_id, title, description, source_surface,
                      requested_by, role, status, priority, assigned_agent_id,
                      NULL::text AS assigned_agent_display_name, required_skills,
                      approval_tier, approval_queue_id, task_graph_id, due_at,
                      started_at, completed_at, blocked_reason,
                      acceptance_criteria, handoff, metadata, created_at, updated_at
            """,
            workspace_id,
            body.title,
            body.description,
            body.source_surface,
            actor,
            body.role,
            body.priority,
            body.assigned_agent_id,
            body.required_skills,
            approval_tier,
            body.due_at,
            json.dumps(body.acceptance_criteria),
            json.dumps(metadata),
        )
        if row is None:
            raise HTTPException(status_code=500, detail="Work item insert failed")
        await conn.execute(
            """
            INSERT INTO public.alpha_agent_work_item_events (
                work_item_id, event_type, actor, to_status, message, metadata
            )
            VALUES ($1, 'created', $2, 'queued', $3, $4::jsonb)
            """,
            row["id"],
            actor,
            "work item queued",
            json.dumps({"source_surface": body.source_surface}),
        )

    logger.info(
        "AGENT_BOARD_WORK_ITEM_CREATED work_item_id=%s assigned_agent_id=%s approval_tier=%s",
        row["id"],
        body.assigned_agent_id,
        approval_tier,
    )
    return _work_item_from_row(row, skills_by_name)


@router.patch("/work-items/{work_item_id}/status", response_model=WorkItemOut)
async def update_work_item_status(
    work_item_id: UUID,
    request: Request,
    body: UpdateWorkItemStatusRequest,
) -> WorkItemOut:
    check_scopes(request, "agents.write", "agent_board.write")
    if body.status == "blocked" and not body.blocked_reason:
        raise HTTPException(status_code=400, detail="blocked_reason is required")

    actor = str(getattr(request.state, "user_id", "unknown"))
    async with rls_connection(request) as conn:
        current = await conn.fetchrow(
            """
            SELECT status
              FROM public.alpha_agent_work_items
             WHERE id = $1
             FOR UPDATE
            """,
            work_item_id,
        )
        if current is None:
            raise HTTPException(status_code=404, detail="Work item not found")

        row = await conn.fetchrow(
            """
            UPDATE public.alpha_agent_work_items
               SET status = $2,
                   blocked_reason = CASE
                     WHEN $2 = 'blocked' THEN $3
                     ELSE NULL
                   END,
                   handoff = handoff || $4::jsonb,
                   metadata = metadata || $5::jsonb,
                   started_at = CASE
                     WHEN $2 = 'in_progress' AND started_at IS NULL THEN NOW()
                     ELSE started_at
                   END,
                   completed_at = CASE
                     WHEN $2 IN ('done', 'cancelled') THEN NOW()
                     ELSE NULL
                   END
             WHERE id = $1
             RETURNING id, workspace_id, title, description, source_surface,
                       requested_by, role, status, priority, assigned_agent_id,
                       (
                         SELECT display_name
                           FROM public.alpha_agents a
                          WHERE a.agent_id = alpha_agent_work_items.assigned_agent_id
                       ) AS assigned_agent_display_name,
                       required_skills, approval_tier, approval_queue_id,
                       task_graph_id, due_at, started_at, completed_at,
                       blocked_reason, acceptance_criteria, handoff, metadata,
                       created_at, updated_at
            """,
            work_item_id,
            body.status,
            body.blocked_reason,
            json.dumps(body.handoff),
            json.dumps(body.metadata),
        )
        if row is None:
            raise HTTPException(status_code=500, detail="Work item update failed")
        await conn.execute(
            """
            INSERT INTO public.alpha_agent_work_item_events (
                work_item_id, event_type, actor, from_status, to_status,
                message, metadata
            )
            VALUES ($1, 'status_changed', $2, $3, $4, $5, $6::jsonb)
            """,
            work_item_id,
            actor,
            current["status"],
            body.status,
            body.blocked_reason or "",
            json.dumps({"handoff_keys": sorted(body.handoff.keys())}),
        )
        skills_by_name = await _load_referenced_skills(conn, [row])

    logger.info(
        "AGENT_BOARD_WORK_ITEM_STATUS_CHANGED work_item_id=%s from_status=%s to_status=%s",
        work_item_id,
        current["status"],
        body.status,
    )
    return _work_item_from_row(row, skills_by_name)
