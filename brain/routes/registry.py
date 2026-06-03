"""Skill and agent registry API."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from brain.agents.manual_run import (
    canonical_agent_id,
    manual_run_eligibility,
    run_agent_now,
)
from brain.db.pool import get_pool
from brain.db.rls import rls_connection
from brain.middleware.scopes import check_scopes
from brain.registry.models import SkillManifestV1
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

router = APIRouter(prefix="/v1", tags=["registry"])


class SkillOut(BaseModel):
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
    owner: str
    manifest: SkillManifestV1 | None = None
    metadata: dict = Field(default_factory=dict)


class SkillListOut(BaseModel):
    count: int
    skills: list[SkillOut]


class AgentOut(BaseModel):
    agent_id: str
    display_name: str
    purpose: str
    risk_tier: str
    status: str
    enabled: bool
    owner: str
    cadence: str | None = None
    launch_label: str | None = None
    allowed_skills: list[str] = Field(default_factory=list)
    allowed_scopes: list[str] = Field(default_factory=list)
    cost_daily_cap_usd: float | None = None
    model_policy: dict = Field(default_factory=dict)
    approval_policy: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class AgentListOut(BaseModel):
    count: int
    agents: list[AgentOut]


class AgentEventOut(BaseModel):
    id: str
    agent_id: str
    run_id: str | None = None
    event_type: str
    severity: str
    title: str
    message: str
    correlation_id: str | None = None
    channel_key: str
    notification_status: str
    notification_error: str | None = None
    payload: dict = Field(default_factory=dict)
    notification_result: dict = Field(default_factory=dict)
    created_at: str
    notified_at: str | None = None


class AgentEventListOut(BaseModel):
    count: int
    events: list[AgentEventOut]


class AgentRunOut(BaseModel):
    id: str
    agent_id: str
    status: str
    trigger_type: str
    trace_id: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    cost_usd: float
    error_text: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: str


class AgentRunListOut(BaseModel):
    count: int
    runs: list[AgentRunOut]


class AgentStatusOut(BaseModel):
    agent_id: str
    display_name: str
    status: str
    enabled: bool
    risk_tier: str
    cadence: str | None = None
    launch_label: str | None = None
    mattermost_channel_key: str | None = None
    last_run_status: str | None = None
    last_run_at: str | None = None
    last_event_type: str | None = None
    last_event_severity: str | None = None
    last_event_title: str | None = None
    last_event_at: str | None = None


class AgentStatusListOut(BaseModel):
    count: int
    agents: list[AgentStatusOut]


class AgentManualRunOut(BaseModel):
    agent_id: str
    executed: bool
    run_id: str | None = None
    status: str | None = None
    trace_id: str | None = None
    skipped_reason: str | None = None
    error_text: str | None = None


def _jsonb(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _skill_from_row(row) -> SkillOut:
    metadata = _jsonb(row["metadata"])
    manifest = metadata.get("manifest")
    return SkillOut(
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
        owner=row["owner"],
        manifest=SkillManifestV1.model_validate(manifest) if manifest else None,
        metadata=metadata,
    )


def _agent_from_row(row) -> AgentOut:
    cost_cap = row["cost_daily_cap_usd"]
    return AgentOut(
        agent_id=row["agent_id"],
        display_name=row["display_name"],
        purpose=row["purpose"],
        risk_tier=row["risk_tier"],
        status=row["status"],
        enabled=row["enabled"],
        owner=row["owner"],
        cadence=row["cadence"],
        launch_label=row["launch_label"],
        allowed_skills=list(row["allowed_skills"] or []),
        allowed_scopes=list(row["allowed_scopes"] or []),
        cost_daily_cap_usd=float(cost_cap) if cost_cap is not None else None,
        model_policy=_jsonb(row["model_policy"]),
        approval_policy=_jsonb(row["approval_policy"]),
        metadata=_jsonb(row["metadata"]),
    )


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _agent_event_from_row(row) -> AgentEventOut:
    return AgentEventOut(
        id=str(row["id"]),
        agent_id=row["agent_id"],
        run_id=str(row["run_id"]) if row["run_id"] else None,
        event_type=row["event_type"],
        severity=row["severity"],
        title=row["title"],
        message=row["message"],
        correlation_id=row["correlation_id"],
        channel_key=row["channel_key"],
        notification_status=row["notification_status"],
        notification_error=row["notification_error"],
        payload=_jsonb(row["payload"]),
        notification_result=_jsonb(row["notification_result"]),
        created_at=_iso(row["created_at"]) or "",
        notified_at=_iso(row["notified_at"]),
    )


def _agent_run_from_row(row) -> AgentRunOut:
    return AgentRunOut(
        id=str(row["id"]),
        agent_id=row["agent_id"],
        status=row["status"],
        trigger_type=row["trigger_type"],
        trace_id=row["trace_id"],
        started_at=_iso(row["started_at"]),
        completed_at=_iso(row["completed_at"]),
        cost_usd=float(row["cost_usd"] or 0),
        error_text=row["error_text"],
        metadata=_jsonb(row["metadata"]),
        created_at=_iso(row["created_at"]) or "",
    )


def _agent_status_from_row(row) -> AgentStatusOut:
    metadata = _jsonb(row["metadata"])
    return AgentStatusOut(
        agent_id=row["agent_id"],
        display_name=row["display_name"],
        status=row["status"],
        enabled=row["enabled"],
        risk_tier=row["risk_tier"],
        cadence=row["cadence"],
        launch_label=row["launch_label"],
        mattermost_channel_key=metadata.get("mattermost_channel_key"),
        last_run_status=row["last_run_status"],
        last_run_at=_iso(row["last_run_at"]),
        last_event_type=row["last_event_type"],
        last_event_severity=row["last_event_severity"],
        last_event_title=row["last_event_title"],
        last_event_at=_iso(row["last_event_at"]),
    )


@router.get("/skills", response_model=SkillListOut)
async def list_skills(
    request: Request,
    domain: str | None = None,
    status: Literal["planned", "active", "disabled", "all"] = Query(default="all"),
) -> SkillListOut:
    check_scopes(request, "skills.read", "agents.read")
    filters: list[str] = []
    params: list[str] = []
    if domain:
        params.append(domain)
        filters.append(f"domain = ${len(params)}")
    if status != "all":
        params.append(status)
        filters.append(f"status = ${len(params)}")
    where = " AND ".join(filters) if filters else "TRUE"

    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            f"""
            SELECT skill_name, domain, action, description, approval_tier, scope,
                   status, mutates_state, body_access, idempotency_required,
                   owner, metadata
            FROM public.alpha_skill_registry
            WHERE {where}
            ORDER BY domain ASC, skill_name ASC
            """,
            *params,
        )
    return SkillListOut(count=len(rows), skills=[_skill_from_row(row) for row in rows])


@router.get("/skills/{skill_name}", response_model=SkillOut)
async def get_skill(skill_name: str, request: Request) -> SkillOut:
    check_scopes(request, "skills.read", "agents.read")
    async with rls_connection(request) as conn:
        row = await conn.fetchrow(
            """
            SELECT skill_name, domain, action, description, approval_tier, scope,
                   status, mutates_state, body_access, idempotency_required,
                   owner, metadata
            FROM public.alpha_skill_registry
            WHERE skill_name = $1
            """,
            skill_name,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Skill not found")
    return _skill_from_row(row)


@router.get("/agents", response_model=AgentListOut)
async def list_agents(
    request: Request,
    status: Literal["planned", "active", "disabled", "all"] = Query(default="all"),
    enabled: bool | None = None,
) -> AgentListOut:
    check_scopes(request, "agents.read")
    filters: list[str] = []
    params: list = []
    if status != "all":
        params.append(status)
        filters.append(f"status = ${len(params)}")
    if enabled is not None:
        params.append(enabled)
        filters.append(f"enabled = ${len(params)}")
    where = " AND ".join(filters) if filters else "TRUE"

    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            f"""
            SELECT agent_id, display_name, purpose, risk_tier, status, enabled,
                   owner, cadence, launch_label, allowed_skills, allowed_scopes,
                   cost_daily_cap_usd, model_policy, approval_policy, metadata
            FROM public.alpha_agents
            WHERE {where}
            ORDER BY status ASC, agent_id ASC
            """,
            *params,
        )
    return AgentListOut(count=len(rows), agents=[_agent_from_row(row) for row in rows])


@router.get("/agents/status", response_model=AgentStatusListOut)
async def list_agent_statuses(request: Request) -> AgentStatusListOut:
    check_scopes(request, "agents.read")
    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            """
            SELECT a.agent_id, a.display_name, a.status, a.enabled, a.risk_tier,
                   a.cadence, a.launch_label, a.metadata,
                   lr.status AS last_run_status,
                   lr.last_run_at AS last_run_at,
                   le.event_type AS last_event_type,
                   le.severity AS last_event_severity,
                   le.title AS last_event_title,
                   le.created_at AS last_event_at
            FROM public.alpha_agents a
            LEFT JOIN LATERAL (
                SELECT
                    status,
                    COALESCE(completed_at, started_at, created_at) AS last_run_at
                FROM public.alpha_agent_runs
                WHERE agent_id = a.agent_id
                ORDER BY COALESCE(completed_at, started_at, created_at) DESC,
                         created_at DESC
                LIMIT 1
            ) lr ON TRUE
            LEFT JOIN LATERAL (
                SELECT event_type, severity, title, created_at
                FROM public.alpha_agent_events
                WHERE agent_id = a.agent_id
                ORDER BY created_at DESC
                LIMIT 1
            ) le ON TRUE
            ORDER BY a.status ASC, a.agent_id ASC
            """
        )
    return AgentStatusListOut(
        count=len(rows),
        agents=[_agent_status_from_row(row) for row in rows],
    )


@router.get("/agents/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: str, request: Request) -> AgentOut:
    check_scopes(request, "agents.read")
    async with rls_connection(request) as conn:
        row = await conn.fetchrow(
            """
            SELECT agent_id, display_name, purpose, risk_tier, status, enabled,
                   owner, cadence, launch_label, allowed_skills, allowed_scopes,
                   cost_daily_cap_usd, model_policy, approval_policy, metadata
            FROM public.alpha_agents
            WHERE agent_id = $1
            """,
            agent_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_from_row(row)


@router.get("/agents/{agent_id}/events", response_model=AgentEventListOut)
async def list_agent_events(
    agent_id: str,
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    severity: Literal[
        "debug", "info", "needs_input", "warning", "error", "critical", "all"
    ] = Query(default="all"),
) -> AgentEventListOut:
    check_scopes(request, "agents.read")
    filters = ["agent_id = $1"]
    params: list = [agent_id]
    if severity != "all":
        params.append(severity)
        filters.append(f"severity = ${len(params)}")
    params.append(limit)
    where = " AND ".join(filters)
    async with rls_connection(request) as conn:
        agent_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM public.alpha_agents WHERE agent_id = $1)",
            agent_id,
        )
        if not agent_exists:
            raise HTTPException(status_code=404, detail="Agent not found")
        rows = await conn.fetch(
            f"""
            SELECT id, agent_id, run_id, event_type, severity, title, message,
                   correlation_id, channel_key, notification_status,
                   notification_error, payload, notification_result, created_at,
                   notified_at
            FROM public.alpha_agent_events
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return AgentEventListOut(
        count=len(rows),
        events=[_agent_event_from_row(row) for row in rows],
    )


@router.get("/agents/{agent_id}/runs", response_model=AgentRunListOut)
async def list_agent_runs(
    agent_id: str,
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
) -> AgentRunListOut:
    check_scopes(request, "agents.read")
    async with rls_connection(request) as conn:
        agent_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM public.alpha_agents WHERE agent_id = $1)",
            agent_id,
        )
        if not agent_exists:
            raise HTTPException(status_code=404, detail="Agent not found")
        rows = await conn.fetch(
            """
            SELECT id, agent_id, status, trigger_type, trace_id, started_at,
                   completed_at, cost_usd, error_text, metadata, created_at
            FROM public.alpha_agent_runs
            WHERE agent_id = $1
            ORDER BY COALESCE(completed_at, started_at, created_at) DESC,
                     created_at DESC
            LIMIT $2
            """,
            agent_id,
            limit,
        )
    return AgentRunListOut(
        count=len(rows), runs=[_agent_run_from_row(row) for row in rows]
    )


@router.post("/agents/{agent_id}/enable", response_model=AgentOut)
async def enable_agent(agent_id: str, request: Request) -> AgentOut:
    check_scopes(request, "agents.write")
    return await _set_agent_enabled(agent_id, request, enabled=True)


@router.post("/agents/{agent_id}/disable", response_model=AgentOut)
async def disable_agent(agent_id: str, request: Request) -> AgentOut:
    check_scopes(request, "agents.write")
    return await _set_agent_enabled(agent_id, request, enabled=False)


@router.post("/agents/{agent_id}/run", response_model=AgentManualRunOut)
async def run_agent(agent_id: str, request: Request) -> AgentManualRunOut:
    check_scopes(request, "agents.write")
    canonical_id = canonical_agent_id(agent_id)
    async with rls_connection(request) as conn:
        row = await conn.fetchrow(
            """
            SELECT agent_id, status, enabled, risk_tier, metadata
            FROM public.alpha_agents
            WHERE agent_id = $1
            """,
            canonical_id,
        )
    eligibility = manual_run_eligibility(
        {
            "agent_id": row["agent_id"],
            "status": row["status"],
            "enabled": row["enabled"],
            "risk_tier": row["risk_tier"],
            "metadata": _jsonb(row["metadata"]),
        }
        if row
        else None
    )
    if not eligibility.allowed:
        status_code = 404 if eligibility.reason == "unknown_agent" else 409
        raise HTTPException(status_code=status_code, detail=eligibility.reason)

    result = await run_agent_now(canonical_id, pool=get_pool())
    logger.info(
        "AGENT_MANUAL_RUN agent_id=%s executed=%s run_id=%s",
        agent_id,
        result.executed,
        result.run_id,
    )
    return AgentManualRunOut(
        agent_id=result.agent_id,
        executed=result.executed,
        run_id=str(result.run_id) if result.run_id else None,
        status=result.status,
        trace_id=result.trace_id,
        skipped_reason=result.skipped_reason,
        error_text=result.error_text,
    )


async def _set_agent_enabled(
    agent_id: str, request: Request, *, enabled: bool
) -> AgentOut:
    actor = str(getattr(request.state, "user_id", "unknown"))
    async with rls_connection(request) as conn:
        row = await conn.fetchrow(
            """
            UPDATE public.alpha_agents
            SET enabled = $2,
                status = CASE
                    WHEN $2 THEN
                        CASE WHEN status = 'disabled' THEN 'planned' ELSE status END
                    ELSE 'disabled'
                END,
                metadata = jsonb_set(
                    metadata,
                    CASE
                        WHEN $2 THEN ARRAY['last_enabled_by']
                        ELSE ARRAY['last_disabled_by']
                    END,
                    to_jsonb($3::text),
                    true
                ),
                updated_at = NOW()
            WHERE agent_id = $1
            RETURNING agent_id, display_name, purpose, risk_tier, status, enabled,
                      owner, cadence, launch_label, allowed_skills, allowed_scopes,
                      cost_daily_cap_usd, model_policy, approval_policy, metadata
            """,
            agent_id,
            enabled,
            actor,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    logger.info("AGENT_REGISTRY_SET_ENABLED agent_id=%s enabled=%s", agent_id, enabled)
    return _agent_from_row(row)
