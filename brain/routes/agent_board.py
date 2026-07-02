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
ExecutorStepType = Literal["llm", "code", "tool"]
RegistryStatusFilter = Literal["planned", "active", "disabled", "all"]
SkillDiscoveryMatchType = Literal["allowed_skill", "allowed_scope"]

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


class SkillDiscoveryAgentOut(BaseModel):
    agent_id: str
    display_name: str
    risk_tier: str
    status: str
    enabled: bool
    match_type: SkillDiscoveryMatchType
    matched_value: str


class SkillDiscoveryEntryOut(BaseModel):
    skill: SkillPolicyOut
    data_classification: str
    side_effect_class: str
    egress_mode: str
    cost_mode: str
    test_ref: str | None = None
    runbook_ref: str | None = None
    candidate_agents: list[SkillDiscoveryAgentOut] = Field(default_factory=list)
    allowed_agent_count: int
    enabled_agent_count: int
    assignment_notes: list[str] = Field(default_factory=list)


class SkillDiscoveryMapOut(BaseModel):
    count: int
    unmapped_skill_count: int
    entries: list[SkillDiscoveryEntryOut]


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


class BridgeWorkItemToTaskGraphRequest(BaseModel):
    step_type: ExecutorStepType = "llm"
    approval_required: bool | None = None
    timeout_seconds: int = Field(default=900, ge=30, le=3600)
    max_retries: int = Field(default=1, ge=0, le=5)


class BridgeWorkItemToTaskGraphOut(BaseModel):
    work_item: WorkItemOut
    task_graph_id: str
    step_id: str | None = None
    dispatch_status: Literal["started", "approval_required", "already_linked"]
    approval_required: bool


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


def _skill_manifest_summary(skill: SkillPolicyOut) -> dict[str, str | None]:
    manifest = skill.metadata.get("manifest")
    if not isinstance(manifest, dict):
        manifest = {}
    egress = manifest.get("egress")
    if not isinstance(egress, dict):
        egress = {}
    cost = manifest.get("cost")
    if not isinstance(cost, dict):
        cost = {}

    return {
        "data_classification": str(manifest.get("data_classification") or "unknown"),
        "side_effect_class": str(
            manifest.get("side_effect_class")
            or ("write" if skill.mutates_state else "read")
        ),
        "egress_mode": str(egress.get("mode") or "unknown"),
        "cost_mode": str(cost.get("mode") or "unknown"),
        "test_ref": manifest.get("test_ref")
        if isinstance(manifest.get("test_ref"), str)
        else None,
        "runbook_ref": manifest.get("runbook_ref")
        if isinstance(manifest.get("runbook_ref"), str)
        else None,
    }


def _skill_agent_match(
    skill: SkillPolicyOut, agent: AgentBoardAgentOut
) -> tuple[SkillDiscoveryMatchType, str] | None:
    if skill.name in agent.allowed_skills:
        return "allowed_skill", skill.name
    if skill.scope in agent.allowed_scopes:
        return "allowed_scope", skill.scope
    return None


def _skill_discovery_entry(
    skill: SkillPolicyOut,
    agents: list[AgentBoardAgentOut],
) -> SkillDiscoveryEntryOut:
    candidate_agents: list[SkillDiscoveryAgentOut] = []
    for agent in agents:
        match = _skill_agent_match(skill, agent)
        if match is None:
            continue
        match_type, matched_value = match
        candidate_agents.append(
            SkillDiscoveryAgentOut(
                agent_id=agent.agent_id,
                display_name=agent.display_name,
                risk_tier=agent.risk_tier,
                status=agent.status,
                enabled=agent.enabled,
                match_type=match_type,
                matched_value=matched_value,
            )
        )

    enabled_agent_count = len(
        [
            agent
            for agent in candidate_agents
            if agent.enabled and agent.status != "disabled"
        ]
    )
    notes: list[str] = []
    if skill.status == "disabled":
        notes.append("skill is disabled")
    if not candidate_agents:
        notes.append("no registered agent advertises this skill")
    elif enabled_agent_count == 0:
        notes.append("no enabled agent advertises this skill")
    if skill.mutates_state and not skill.idempotency_required:
        notes.append("mutating skill is missing idempotency requirement")

    summary = _skill_manifest_summary(skill)
    return SkillDiscoveryEntryOut(
        skill=skill,
        data_classification=summary["data_classification"] or "unknown",
        side_effect_class=summary["side_effect_class"] or "unknown",
        egress_mode=summary["egress_mode"] or "unknown",
        cost_mode=summary["cost_mode"] or "unknown",
        test_ref=summary["test_ref"],
        runbook_ref=summary["runbook_ref"],
        candidate_agents=candidate_agents,
        allowed_agent_count=len(candidate_agents),
        enabled_agent_count=enabled_agent_count,
        assignment_notes=notes,
    )


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


def _work_item_executor_context(row: Any) -> dict[str, Any]:
    return {
        "work_item_id": str(row["id"]),
        "workspace_id": row["workspace_id"],
        "title": row["title"],
        "description": row["description"],
        "source_surface": row["source_surface"],
        "requested_by": row["requested_by"],
        "role": row["role"],
        "priority": row["priority"],
        "assigned_agent_id": row["assigned_agent_id"],
        "required_skills": list(row["required_skills"] or []),
        "approval_tier": row["approval_tier"],
        "acceptance_criteria": _jsonb_list(row["acceptance_criteria"]),
        "handoff": _jsonb_dict(row["handoff"]),
        "metadata": _jsonb_dict(row["metadata"]),
        "due_at": _iso(row["due_at"]),
    }


def _executor_prompt(row: Any) -> str:
    context = _work_item_executor_context(row)
    acceptance = context["acceptance_criteria"] or ["Produce a concise handoff."]
    return (
        "Execute this Alpha Agent Board work item.\n\n"
        f"Title: {context['title']}\n"
        f"Role: {context['role']}\n"
        f"Description: {context['description']}\n"
        f"Required skills: {', '.join(context['required_skills']) or 'none'}\n"
        "Acceptance criteria:\n"
        + "\n".join(f"- {item}" for item in acceptance)
        + "\n\nReturn a result that can be used as an operator handoff."
    )


def _executor_step_input(row: Any, step_type: ExecutorStepType) -> dict[str, Any]:
    if step_type == "tool":
        required_skills = list(row["required_skills"] or [])
        if not required_skills:
            raise HTTPException(
                status_code=400,
                detail="tool step requires at least one required skill",
            )
        return {
            "tool_name": required_skills[0],
            "params": {"work_item": _work_item_executor_context(row)},
        }
    if step_type == "code":
        return {"prompt": _executor_prompt(row), "language": "python"}
    return {"prompt": _executor_prompt(row), "model": "llama3.1:8b"}


def _bridge_requires_step_approval(
    row: Any,
    body: BridgeWorkItemToTaskGraphRequest,
) -> bool:
    forced_by_policy = (
        _TIER_RANK[row["approval_tier"]] >= _TIER_RANK["T3"] or body.step_type == "tool"
    )
    if body.approval_required is False and forced_by_policy:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "approval_required_by_policy",
                "approval_tier": row["approval_tier"],
                "step_type": body.step_type,
            },
        )
    return (
        forced_by_policy if body.approval_required is None else body.approval_required
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


@router.get("/skill-map", response_model=SkillDiscoveryMapOut)
async def get_agent_board_skill_map(
    request: Request,
    query: str | None = Query(default=None, max_length=120),
    domain: str | None = Query(default=None),
    status: RegistryStatusFilter = Query(default="all"),
    limit: int = Query(default=100, ge=1, le=500),
) -> SkillDiscoveryMapOut:
    check_scopes(request, "agents.read", "skills.read", "agent_board.read")
    filters: list[str] = []
    params: list[Any] = []
    if domain:
        params.append(domain)
        filters.append(f"domain = ${len(params)}")
    if status != "all":
        params.append(status)
        filters.append(f"status = ${len(params)}")
    if query and query.strip():
        params.append(f"%{query.strip()}%")
        param = f"${len(params)}"
        filters.append(
            "("
            f"skill_name ILIKE {param} OR domain ILIKE {param} "
            f"OR action ILIKE {param} OR scope ILIKE {param} "
            f"OR description ILIKE {param}"
            ")"
        )
    params.append(limit)
    limit_param = f"${len(params)}"
    where = " AND ".join(filters) if filters else "TRUE"

    async with rls_connection(request) as conn:
        skill_rows = await conn.fetch(
            f"""
            SELECT skill_name, domain, action, description, approval_tier, scope,
                   status, mutates_state, body_access, idempotency_required, metadata
              FROM public.alpha_skill_registry
             WHERE {where}
             ORDER BY domain ASC, skill_name ASC
             LIMIT {limit_param}
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
    entries = [_skill_discovery_entry(skill, agents) for skill in skills]
    return SkillDiscoveryMapOut(
        count=len(entries),
        unmapped_skill_count=len(
            [entry for entry in entries if entry.allowed_agent_count == 0]
        ),
        entries=entries,
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


@router.post(
    "/work-items/{work_item_id}/task-graph",
    response_model=BridgeWorkItemToTaskGraphOut,
)
async def bridge_work_item_to_task_graph(
    work_item_id: UUID,
    request: Request,
    body: BridgeWorkItemToTaskGraphRequest,
) -> BridgeWorkItemToTaskGraphOut:
    check_scopes(request, "agents.write", "agent_board.write")
    actor = str(getattr(request.state, "user_id", "unknown"))

    async with rls_connection(request) as conn:
        async with conn.transaction():
            current = await conn.fetchrow(
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
                 FOR UPDATE OF wi
                """,
                work_item_id,
            )
            if current is None:
                raise HTTPException(status_code=404, detail="Work item not found")

            skills_by_name = await _load_referenced_skills(conn, [current])
            if current["task_graph_id"]:
                work_item = _work_item_from_row(current, skills_by_name)
                bridge = work_item.metadata.get("executor_bridge")
                linked_approval_required = (
                    bool(bridge.get("approval_required"))
                    if isinstance(bridge, dict)
                    else _TIER_RANK[current["approval_tier"]] >= _TIER_RANK["T3"]
                )
                return BridgeWorkItemToTaskGraphOut(
                    work_item=work_item,
                    task_graph_id=str(current["task_graph_id"]),
                    dispatch_status="already_linked",
                    approval_required=linked_approval_required,
                )

            if current["status"] not in {
                "queued",
                "needs_approval",
                "handoff_ready",
            }:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "work_item_not_dispatchable",
                        "status": current["status"],
                    },
                )

            approval_required = _bridge_requires_step_approval(current, body)
            graph_metadata = {
                "source": "agent_board",
                "work_item_id": str(current["id"]),
                "assigned_agent_id": current["assigned_agent_id"],
                "required_skills": list(current["required_skills"] or []),
                "approval_tier": current["approval_tier"],
            }
            graph_row = await conn.fetchrow(
                """
                INSERT INTO public.alpha_task_graphs (
                    user_id, title, description, graph_type, user_type,
                    content_tier, priority, metadata, source, ci_required
                )
                VALUES (
                    $1, $2, $3, 'agent', 'adult',
                    'unrestricted', $4, $5::jsonb, 'agent', false
                )
                RETURNING id
                """,
                actor,
                f"Agent Board: {current['title']}",
                current["description"],
                current["priority"],
                json.dumps(graph_metadata),
            )
            if graph_row is None:
                raise HTTPException(status_code=500, detail="Task graph insert failed")

            step_row = await conn.fetchrow(
                """
                INSERT INTO public.alpha_task_steps (
                    graph_id, user_id, step_name, step_type, step_order,
                    status, content_tier, input, approval_required,
                    timeout_seconds, max_retries
                )
                VALUES (
                    $1, $2, $3, $4, 1,
                    'pending', 'unrestricted', $5::jsonb, $6,
                    $7, $8
                )
                RETURNING id
                """,
                graph_row["id"],
                actor,
                current["title"],
                body.step_type,
                json.dumps(_executor_step_input(current, body.step_type)),
                approval_required,
                body.timeout_seconds,
                body.max_retries,
            )
            if step_row is None:
                raise HTTPException(status_code=500, detail="Task step insert failed")

            next_status: WorkItemStatus = (
                "needs_approval" if approval_required else "in_progress"
            )
            bridge_metadata = {
                "executor_bridge": {
                    "task_graph_id": str(graph_row["id"]),
                    "step_id": str(step_row["id"]),
                    "step_type": body.step_type,
                    "approval_required": approval_required,
                    "dispatched_by": actor,
                }
            }
            row = await conn.fetchrow(
                """
                UPDATE public.alpha_agent_work_items
                   SET task_graph_id = $2,
                       status = $3,
                       metadata = metadata || $4::jsonb,
                       started_at = CASE
                         WHEN $3 = 'in_progress' AND started_at IS NULL THEN NOW()
                         ELSE started_at
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
                graph_row["id"],
                next_status,
                json.dumps(bridge_metadata),
            )
            if row is None:
                raise HTTPException(status_code=500, detail="Work item update failed")

            await conn.execute(
                """
                INSERT INTO public.alpha_agent_work_item_events (
                    work_item_id, event_type, actor, from_status, to_status,
                    message, metadata
                )
                VALUES ($1, 'task_graph_linked', $2, $3, $4, $5, $6::jsonb)
                """,
                work_item_id,
                actor,
                current["status"],
                next_status,
                "task graph linked and executor notified",
                json.dumps(bridge_metadata["executor_bridge"]),
            )
            await conn.execute(
                "SELECT pg_notify('graph_submitted', $1::text)",
                str(graph_row["id"]),
            )

    logger.info(
        "AGENT_BOARD_TASK_GRAPH_LINKED work_item_id=%s task_graph_id=%s approval_required=%s",
        work_item_id,
        graph_row["id"],
        approval_required,
    )
    return BridgeWorkItemToTaskGraphOut(
        work_item=_work_item_from_row(row, skills_by_name),
        task_graph_id=str(graph_row["id"]),
        step_id=str(step_row["id"]),
        dispatch_status="approval_required" if approval_required else "started",
        approval_required=approval_required,
    )


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
