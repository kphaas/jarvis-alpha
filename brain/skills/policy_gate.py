"""Runtime policy gate for agent-to-skill calls.

The registry is the durable control plane. This module is the runtime guard:
agents ask it before invoking a skill, and it returns allow, deny, or
approval_required. It deliberately does not execute the skill.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

PolicyOutcome = Literal["allow", "approval_required", "deny"]

APPROVAL_TIERS = {"T4", "T5"}
BODY_SCOPE_BY_DOMAIN = {
    "gmail": "email.body.read",
    "email": "email.body.read",
    "imessage": "imessage.body.read",
}


@dataclass(frozen=True, slots=True)
class SkillInvocation:
    """An agent's requested skill call before adapter execution."""

    agent_id: str
    skill_name: str
    estimated_cost_usd: Decimal = Decimal("0")
    idempotency_key: str | None = None
    body_access: bool = False
    approval_granted: bool = False


@dataclass(frozen=True, slots=True)
class SkillPolicyDecision:
    """Decision returned by the policy gate."""

    outcome: PolicyOutcome
    reason: str
    agent_id: str
    skill_name: str
    approval_tier: str | None = None
    skill_scope: str | None = None
    body_scope: str | None = None
    cost_daily_cap_usd: Decimal | None = None
    cost_spent_today_usd: Decimal = Decimal("0")
    estimated_cost_usd: Decimal = Decimal("0")

    @property
    def allowed(self) -> bool:
        return self.outcome == "allow"

    @property
    def requires_approval(self) -> bool:
        return self.outcome == "approval_required"


class SkillPolicyGate:
    """Evaluate agent registry policy before a skill adapter runs."""

    async def evaluate(
        self, conn: Any, invocation: SkillInvocation
    ) -> SkillPolicyDecision:
        agent_row = await conn.fetchrow(
            """
            SELECT agent_id, status, enabled, allowed_skills, allowed_scopes,
                   cost_daily_cap_usd
            FROM public.alpha_agents
            WHERE agent_id = $1
            """,
            invocation.agent_id,
        )
        skill_row = await conn.fetchrow(
            """
            SELECT skill_name, domain, approval_tier, scope, status,
                   mutates_state, body_access, idempotency_required, metadata
            FROM public.alpha_skill_registry
            WHERE skill_name = $1
            """,
            invocation.skill_name,
        )

        spent_today = Decimal("0")
        if agent_row and _decimal_or_none(_row_value(agent_row, "cost_daily_cap_usd")):
            spent_row = await conn.fetchrow(
                """
                SELECT COALESCE(SUM(cost_usd), 0) AS spent_usd
                FROM public.alpha_agent_runs
                WHERE agent_id = $1
                  AND created_at >= date_trunc('day', NOW())
                """,
                invocation.agent_id,
            )
            spent_today = _decimal_or_zero(_row_value(spent_row, "spent_usd"))

        return self.evaluate_rows(
            invocation=invocation,
            agent_row=agent_row,
            skill_row=skill_row,
            spent_today_usd=spent_today,
        )

    def evaluate_rows(
        self,
        *,
        invocation: SkillInvocation,
        agent_row: Any,
        skill_row: Any,
        spent_today_usd: Decimal = Decimal("0"),
    ) -> SkillPolicyDecision:
        if not agent_row:
            return _deny(invocation, "unknown_agent")
        if not skill_row:
            return _deny(invocation, "unknown_skill")

        skill_scope = str(_row_value(skill_row, "scope"))
        approval_tier = str(_row_value(skill_row, "approval_tier"))
        body_scope = _body_scope_for(skill_row)
        cost_cap = _decimal_or_none(_row_value(agent_row, "cost_daily_cap_usd"))
        estimated_cost = _decimal_or_zero(invocation.estimated_cost_usd)

        base = {
            "approval_tier": approval_tier,
            "skill_scope": skill_scope,
            "body_scope": body_scope,
            "cost_daily_cap_usd": cost_cap,
            "cost_spent_today_usd": spent_today_usd,
            "estimated_cost_usd": estimated_cost,
        }

        if estimated_cost < 0:
            return _deny(invocation, "invalid_estimated_cost", **base)
        if not bool(_row_value(agent_row, "enabled")):
            return _deny(invocation, "agent_disabled", **base)
        if _row_value(agent_row, "status") != "active":
            return _deny(invocation, "agent_not_active", **base)
        if _row_value(skill_row, "status") != "active":
            return _deny(invocation, "skill_not_active", **base)

        allowed_skills = _as_list(_row_value(agent_row, "allowed_skills"))
        if "*" not in allowed_skills and invocation.skill_name not in allowed_skills:
            return _deny(invocation, "skill_not_allowed_for_agent", **base)

        allowed_scopes = _as_list(_row_value(agent_row, "allowed_scopes"))
        if "*" not in allowed_scopes and skill_scope not in allowed_scopes:
            return _deny(invocation, "scope_not_allowed_for_agent", **base)

        if invocation.body_access:
            if not bool(_row_value(skill_row, "body_access")):
                return _deny(invocation, "body_access_not_supported", **base)
            if "*" not in allowed_scopes and body_scope not in allowed_scopes:
                return _deny(invocation, "body_scope_not_allowed_for_agent", **base)

        if (
            bool(_row_value(skill_row, "mutates_state"))
            and bool(_row_value(skill_row, "idempotency_required"))
            and not invocation.idempotency_key
        ):
            return _deny(invocation, "idempotency_key_required", **base)

        if cost_cap is not None and spent_today_usd + estimated_cost > cost_cap:
            return _deny(invocation, "cost_cap_exceeded", **base)

        if approval_tier in APPROVAL_TIERS and not invocation.approval_granted:
            return SkillPolicyDecision(
                outcome="approval_required",
                reason=f"{approval_tier.lower()}_approval_required",
                agent_id=invocation.agent_id,
                skill_name=invocation.skill_name,
                **base,
            )

        return SkillPolicyDecision(
            outcome="allow",
            reason="policy_ok",
            agent_id=invocation.agent_id,
            skill_name=invocation.skill_name,
            **base,
        )


def _deny(
    invocation: SkillInvocation,
    reason: str,
    **kwargs: Any,
) -> SkillPolicyDecision:
    return SkillPolicyDecision(
        outcome="deny",
        reason=reason,
        agent_id=invocation.agent_id,
        skill_name=invocation.skill_name,
        **kwargs,
    )


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence):
        return [str(item) for item in value]
    return []


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _decimal_or_zero(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _body_scope_for(skill_row: Any) -> str:
    metadata = _row_value(skill_row, "metadata") or {}
    if isinstance(metadata, Mapping) and metadata.get("body_scope"):
        return str(metadata["body_scope"])
    domain = str(_row_value(skill_row, "domain") or "")
    return BODY_SCOPE_BY_DOMAIN.get(domain, f"{domain}.body.read")
