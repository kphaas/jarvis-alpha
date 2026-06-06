"""Helm read-only Alpha summary proxy."""

from __future__ import annotations

from datetime import UTC, datetime
from collections.abc import Mapping
from typing import Protocol, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from brain.db.rls import platform_admin_connection
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes

router = APIRouter(prefix="/v1/helm", tags=["helm"])

_SECURITY_AGENT_IDS = (
    "warden",
    "porchlight",
    "keyturner",
    "sweep",
    "tripwire",
    "ledger",
)


class RowLike(Protocol):
    def __getitem__(self, key: str) -> object: ...


class HelmApprovalSummary(BaseModel):
    pending_total: int
    by_tier: dict[str, int] = Field(default_factory=dict)
    highest_tier: str | None = None


class HelmSkillRegistrySummary(BaseModel):
    total: int
    by_status: dict[str, int] = Field(default_factory=dict)
    mutating: int
    body_access: int


class HelmAgentRegistrySummary(BaseModel):
    total: int
    enabled: int
    by_status: dict[str, int] = Field(default_factory=dict)
    by_risk_tier: dict[str, int] = Field(default_factory=dict)


class HelmRegistrySummary(BaseModel):
    skills: HelmSkillRegistrySummary
    agents: HelmAgentRegistrySummary


class HelmGatewayPosture(BaseModel):
    state: str
    active: bool


class HelmSecurityAgentSummary(BaseModel):
    total: int
    enabled: int
    by_status: dict[str, int] = Field(default_factory=dict)


class HelmPostureSummary(BaseModel):
    gateway: HelmGatewayPosture
    security_agents: HelmSecurityAgentSummary


class HelmControlSummary(BaseModel):
    mode: str = "read_only"
    alpha_authority: str = "required"
    mutations: str = "disabled"


class HelmSummaryOut(BaseModel):
    service: str = "jarvis-alpha"
    generated_at: str
    approvals: HelmApprovalSummary
    registry: HelmRegistrySummary
    posture: HelmPostureSummary
    controls: HelmControlSummary = Field(default_factory=HelmControlSummary)


def _row_value(row: object, key: str, default: object | None = None) -> object | None:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return cast(RowLike, row)[key]
    except (KeyError, TypeError):
        return default


def _str_value(row: object, key: str, default: str) -> str:
    value = _row_value(row, key, default)
    return str(value or default)


def _int_value(row: object, key: str) -> int:
    value = _row_value(row, key, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float | str | bytes | bytearray):
        return int(value or 0)
    return 0


def _bool_value(row: object, key: str) -> bool:
    return bool(_row_value(row, key, False))


def _risk_rank(tier: str) -> int:
    order = {"T1": 1, "T2": 2, "T3": 3, "T4": 4, "T5": 5}
    return order.get(tier, 0)


def _approval_summary(rows: list[object]) -> HelmApprovalSummary:
    by_tier: dict[str, int] = {}
    for row in rows:
        tier = _str_value(row, "risk_tier", "unclassified")
        count = _int_value(row, "count")
        by_tier[tier] = count

    highest = max(by_tier, key=_risk_rank) if by_tier else None
    return HelmApprovalSummary(
        pending_total=sum(by_tier.values()),
        by_tier=by_tier,
        highest_tier=highest,
    )


def _skill_summary(rows: list[object]) -> HelmSkillRegistrySummary:
    by_status: dict[str, int] = {}
    total = 0
    mutating = 0
    body_access = 0
    for row in rows:
        status = _str_value(row, "status", "unknown")
        count = _int_value(row, "count")
        by_status[status] = count
        total += count
        mutating += _int_value(row, "mutating")
        body_access += _int_value(row, "body_access")

    return HelmSkillRegistrySummary(
        total=total,
        by_status=by_status,
        mutating=mutating,
        body_access=body_access,
    )


def _agent_summary(rows: list[object]) -> HelmAgentRegistrySummary:
    by_status: dict[str, int] = {}
    by_risk_tier: dict[str, int] = {}
    total = 0
    enabled = 0
    for row in rows:
        count = _int_value(row, "count")
        status = _str_value(row, "status", "unknown")
        risk_tier = _str_value(row, "risk_tier", "unclassified")
        is_enabled = _bool_value(row, "enabled")

        total += count
        if is_enabled:
            enabled += count
        by_status[status] = by_status.get(status, 0) + count
        by_risk_tier[risk_tier] = by_risk_tier.get(risk_tier, 0) + count

    return HelmAgentRegistrySummary(
        total=total,
        enabled=enabled,
        by_status=by_status,
        by_risk_tier=by_risk_tier,
    )


def _gateway_posture(row: object | None) -> HelmGatewayPosture:
    if not row:
        return HelmGatewayPosture(state="missing", active=False)
    active = _bool_value(row, "is_active")
    return HelmGatewayPosture(
        state="registered" if active else "inactive", active=active
    )


def _security_agent_summary(rows: list[object]) -> HelmSecurityAgentSummary:
    by_status: dict[str, int] = {}
    enabled = 0
    for row in rows:
        status = _str_value(row, "status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        if _bool_value(row, "enabled"):
            enabled += 1

    return HelmSecurityAgentSummary(
        total=len(rows),
        enabled=enabled,
        by_status=by_status,
    )


@router.get("/summary", response_model=HelmSummaryOut)
async def helm_summary(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> HelmSummaryOut:
    """Return a redacted, read-only Alpha summary for Helm."""
    check_scopes(request, "helm.read", "admin")
    actor = str(getattr(request.state, "user_id", "unknown"))

    async with platform_admin_connection(
        source="http",
        audit_actor=f"helm_summary:{actor}",
    ) as conn:
        approval_rows = await conn.fetch(
            """
            SELECT COALESCE(risk_tier, 'unclassified') AS risk_tier,
                   COUNT(*)::INTEGER AS count
            FROM public.alpha_approval_queue
            WHERE status = 'pending'
              AND (expires_at IS NULL OR expires_at > NOW())
            GROUP BY COALESCE(risk_tier, 'unclassified')
            ORDER BY risk_tier ASC
            """
        )
        skill_rows = await conn.fetch(
            """
            SELECT COALESCE(status, 'unknown') AS status,
                   COUNT(*)::INTEGER AS count,
                   COUNT(*) FILTER (WHERE mutates_state)::INTEGER AS mutating,
                   COUNT(*) FILTER (WHERE body_access)::INTEGER AS body_access
            FROM public.alpha_skill_registry
            GROUP BY COALESCE(status, 'unknown')
            ORDER BY status ASC
            """
        )
        agent_rows = await conn.fetch(
            """
            SELECT COALESCE(status, 'unknown') AS status,
                   COALESCE(risk_tier, 'unclassified') AS risk_tier,
                   enabled,
                   COUNT(*)::INTEGER AS count
            FROM public.alpha_agents
            GROUP BY COALESCE(status, 'unknown'), COALESCE(risk_tier, 'unclassified'), enabled
            ORDER BY status ASC, risk_tier ASC, enabled DESC
            """
        )
        gateway_row = await conn.fetchrow(
            """
            SELECT is_active
            FROM public.alpha_node_registry
            WHERE name = 'gateway'
            LIMIT 1
            """
        )
        security_agent_rows = await conn.fetch(
            """
            SELECT status, enabled
            FROM public.alpha_agents
            WHERE agent_id = ANY($1::TEXT[])
            ORDER BY agent_id ASC
            """,
            list(_SECURITY_AGENT_IDS),
        )

    return HelmSummaryOut(
        generated_at=datetime.now(UTC).isoformat(),
        approvals=_approval_summary(list(approval_rows)),
        registry=HelmRegistrySummary(
            skills=_skill_summary(list(skill_rows)),
            agents=_agent_summary(list(agent_rows)),
        ),
        posture=HelmPostureSummary(
            gateway=_gateway_posture(gateway_row),
            security_agents=_security_agent_summary(list(security_agent_rows)),
        ),
    )
