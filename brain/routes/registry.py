"""Skill and agent registry API."""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from brain.db.rls import rls_connection
from brain.middleware.scopes import check_scopes
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


def _jsonb(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _skill_from_row(row) -> SkillOut:
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
        metadata=_jsonb(row["metadata"]),
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


@router.post("/agents/{agent_id}/enable", response_model=AgentOut)
async def enable_agent(agent_id: str, request: Request) -> AgentOut:
    check_scopes(request, "agents.write")
    return await _set_agent_enabled(agent_id, request, enabled=True)


@router.post("/agents/{agent_id}/disable", response_model=AgentOut)
async def disable_agent(agent_id: str, request: Request) -> AgentOut:
    check_scopes(request, "agents.write")
    return await _set_agent_enabled(agent_id, request, enabled=False)


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
