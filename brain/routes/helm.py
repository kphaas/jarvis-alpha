"""Helm read-only Alpha summary proxy."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, cast
from uuid import uuid4

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

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
_FAMILY_HELM_SCOPE = "family.helm.read"
_HELM_ACTION_CONNECTORS = frozenset(
    {
        "alpha",
        "forge",
        "family",
        "financial",
        "medical",
        "privacy",
        "spark",
        "herald",
        "warden",
    }
)
_HELM_RISK_TIERS = {"T1", "T2", "T3", "T4", "T5"}


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


class HelmActionProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_id: str = Field(min_length=1, max_length=64)
    action_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=1, max_length=80)
    risk_tier: Literal["T1", "T2", "T3", "T4", "T5"]
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=160)
    payload: dict[str, Any] = Field(default_factory=dict)


class HelmActionProposalOut(BaseModel):
    status: Literal["pending"]
    approval_queue_id: str
    connector_id: str
    action_id: str
    risk_tier: str


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


def _family_base_url() -> str:
    value = os.environ.get("JARVIS_FAMILY_API_URL", "").strip()
    if not value:
        raise HTTPException(status_code=503, detail="family_api_not_configured")
    return value.rstrip("/")


def _family_id() -> str:
    value = os.environ.get("JARVIS_FAMILY_ID", "").strip()
    if not value:
        raise HTTPException(status_code=503, detail="family_id_not_configured")
    return value


def _family_verify_tls() -> bool:
    return os.environ.get("JARVIS_FAMILY_VERIFY_TLS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _family_service_private_key() -> str:
    configured = (
        os.environ.get("ALPHA_FAMILY_SERVICE_PRIVATE_KEY_PATH", "").strip()
        or os.environ.get("JARVIS_ALPHA_SERVICE_PRIVATE_KEY_PATH", "").strip()
    )
    key_path = (
        Path(configured).expanduser()
        if configured
        else Path.home() / "jarvis/pki/services/brain_private.pem"
    )
    return key_path.read_text(encoding="utf-8")


def _family_service_token() -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": os.environ.get("JARVIS_ALPHA_SERVICE_SUB", "brain"),
        "iss": os.environ.get("JARVIS_ALPHA_SERVICE_ISS", "brain"),
        "actor_type": "service",
        "family_id": _family_id(),
        "scopes": [_FAMILY_HELM_SCOPE],
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + 300,
    }
    return jwt.encode(payload, _family_service_private_key(), algorithm="RS256")


def _proposal_parameters_hash(body: HelmActionProposalRequest) -> str:
    canonical = json.dumps(
        body.model_dump(exclude={"idempotency_key"}),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _proposal_nonce(body: HelmActionProposalRequest) -> str:
    if body.idempotency_key:
        return body.idempotency_key
    return f"helm:{body.connector_id}:{body.action_id}:{_proposal_parameters_hash(body)[:16]}"


def _validate_action_proposal(body: HelmActionProposalRequest) -> None:
    if body.connector_id not in _HELM_ACTION_CONNECTORS:
        raise HTTPException(status_code=400, detail="unsupported_connector")
    if body.risk_tier not in _HELM_RISK_TIERS:
        raise HTTPException(status_code=400, detail="unsupported_risk_tier")


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


@router.get("/family/summary")
async def helm_family_summary(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> dict[str, Any]:
    """Return a Family home summary through Alpha-held service identity."""
    check_scopes(request, "helm.read", "admin")
    actor = str(getattr(request.state, "user_id", "unknown"))

    try:
        async with httpx.AsyncClient(
            timeout=5.0,
            verify=_family_verify_tls(),
        ) as client:
            response = await client.get(
                f"{_family_base_url()}/v1/helm/home-summary",
                headers={"Authorization": f"Bearer {_family_service_token()}"},
            )
    except OSError as exc:
        raise HTTPException(
            status_code=503, detail="family_summary_unavailable"
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="family_summary_unavailable"
        ) from exc

    if response.status_code == 401 or response.status_code == 403:
        raise HTTPException(status_code=502, detail="family_service_scope_rejected")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail="family_summary_unavailable")

    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="family_summary_invalid")

    return {
        **payload,
        "_broker": {
            "authority": "jarvis-alpha",
            "source": "jarvis-family",
            "actor": actor,
            "mode": "service_scope",
        },
    }


@router.post("/actions/propose", response_model=HelmActionProposalOut)
async def helm_action_proposal(
    request: Request,
    body: HelmActionProposalRequest,
    _user_id: str = Depends(require_auth),
) -> HelmActionProposalOut:
    """Queue a Helm-proposed action into Alpha's approval queue."""
    check_scopes(request, "helm.read", "admin")
    _validate_action_proposal(body)

    actor_sub = str(getattr(request.state, "user_id", "unknown"))
    actor_type = str(getattr(request.state, "actor_type", "user"))
    parameters_hash = _proposal_parameters_hash(body)
    nonce = _proposal_nonce(body)
    description = f"Helm proposal: {body.domain} - {body.title}"

    async with platform_admin_connection(
        source="http",
        audit_actor=f"helm_action:{actor_sub}",
    ) as conn:
        existing = await conn.fetchrow(
            """
            SELECT id, risk_tier
            FROM public.alpha_approval_queue
            WHERE nonce = $1
               OR (actor_sub = $2 AND parameters_hash = $3 AND status = 'pending')
            ORDER BY requested_at DESC
            LIMIT 1
            """,
            nonce,
            actor_sub,
            parameters_hash,
        )
        if existing is not None:
            return HelmActionProposalOut(
                status="pending",
                approval_queue_id=str(existing["id"]),
                connector_id=body.connector_id,
                action_id=body.action_id,
                risk_tier=str(existing["risk_tier"]),
            )

        queue_id = await conn.fetchval(
            """
            SELECT public.enqueue_approval_request(
                $1::text[], $2::text, $3::text, $4::text, $5::text, $6::text, $7::text
            )
            """,
            ["helm_action_proposal", f"connector:{body.connector_id}"],
            body.risk_tier,
            actor_sub,
            actor_type,
            description,
            parameters_hash,
            nonce,
        )

    if queue_id is None:
        raise HTTPException(status_code=500, detail="approval_queue_write_failed")

    return HelmActionProposalOut(
        status="pending",
        approval_queue_id=str(queue_id),
        connector_id=body.connector_id,
        action_id=body.action_id,
        risk_tier=body.risk_tier,
    )
