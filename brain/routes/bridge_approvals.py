from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from jwt import InvalidTokenError
from pydantic import BaseModel, ConfigDict, Field

from brain.db.rls import RLSContext, rls_context_connection
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

router = APIRouter(prefix="/v1/bridge", tags=["bridge-approvals"])

_DEFAULT_FINANCIAL_PUBLIC_KEY = "~/jarvis/pki/services/jarvis-fin-agent_public.pem"
_DEFAULT_ALPHA_PRIVATE_KEY = "~/jarvis/pki/jwt/jwt_private.pem"
_FINANCIAL_ISSUER = "jarvis-fin-agent"
_BRIDGE_AUDIENCE = "jarvis-alpha-bridge"

BridgeStatus = Literal["pending", "auto_approved", "approved", "rejected", "expired"]


@dataclass(frozen=True, slots=True)
class BridgeClaims:
    sub: str
    iss: str
    domain: str
    domain_version: str


class BridgeApprovalSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    envelope_version: str
    domain: str
    domain_version: str
    intent_kind: Literal["trade_proposal"]
    tier_requested: Literal["T1", "T2", "T3", "T4", "T5"]
    expires_at_window_seconds: int = Field(ge=1, le=3600)
    caller_idempotency_key: str = Field(min_length=8, max_length=128)
    trace_id: str = Field(min_length=8, max_length=128)
    service_caller: str
    submitted_at: datetime
    payload: dict[str, Any]


class BridgeApprovalResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval_id: str
    status: BridgeStatus
    tier_assigned: str
    intent_token: str | None = None
    intent_expires_at: datetime | None = None
    decided_at: datetime | None = None
    decided_by: str | None = None
    rejection_reason: str | None = None


class BridgePendingApproval(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval_id: str
    action_class: list[str]
    status: BridgeStatus
    tier_assigned: str
    actor_sub: str
    actor_type: str
    description: str
    requested_at: datetime | None = None
    expires_at: datetime | None = None
    overnight: bool


class BridgePendingApprovalsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    pending: list[BridgePendingApproval]
    count: int


def _require_financial_bridge_service(request: Request) -> BridgeClaims:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    token = auth.removeprefix("Bearer ").strip()
    try:
        payload = jwt.decode(
            token,
            _financial_public_key(),
            algorithms=["RS256"],
            audience=_BRIDGE_AUDIENCE,
        )
    except InvalidTokenError as exc:
        logger.warning("bridge_auth_failed reason=%s", exc)
        raise HTTPException(status_code=401, detail="invalid_bridge_token")

    if (
        payload.get("iss") != _FINANCIAL_ISSUER
        or payload.get("sub") != _FINANCIAL_ISSUER
    ):
        raise HTTPException(status_code=403, detail="bridge_caller_not_allowed")
    if payload.get("domain") != "jarvis-financial":
        raise HTTPException(status_code=403, detail="bridge_domain_not_allowed")
    return BridgeClaims(
        sub=str(payload["sub"]),
        iss=str(payload["iss"]),
        domain=str(payload.get("domain", "")),
        domain_version=str(payload.get("domain_version", "")),
    )


@router.get("/health")
async def bridge_health(
    claims: BridgeClaims = Depends(_require_financial_bridge_service),
):
    return {
        "status": "ok",
        "service": "jarvis-alpha-bridge",
        "caller": claims.sub,
        "domain": claims.domain,
    }


@router.get("/approvals/pending", response_model=BridgePendingApprovalsResponse)
async def list_bridge_pending_approvals(
    claims: BridgeClaims = Depends(_require_financial_bridge_service),
) -> BridgePendingApprovalsResponse:
    async with rls_context_connection(
        RLSContext.platform_admin(
            source="http",
            audit_actor=f"bridge:{claims.sub}",
            user_id=claims.sub,
        )
    ) as conn:
        rows = await conn.fetch(
            """
            SELECT id, action_class, risk_tier, actor_sub, actor_type,
                   description, status, requested_at, expires_at, overnight
              FROM public.alpha_approval_queue
             WHERE status = 'pending'
               AND expires_at > NOW()
               AND actor_sub = $1
             ORDER BY requested_at ASC
            """,
            claims.sub,
        )
    pending = [_row_to_pending(item) for item in rows]
    return BridgePendingApprovalsResponse(pending=pending, count=len(pending))


@router.post("/approvals/submit", response_model=BridgeApprovalResponse)
async def submit_bridge_approval(
    body: BridgeApprovalSubmitRequest,
    claims: BridgeClaims = Depends(_require_financial_bridge_service),
) -> BridgeApprovalResponse:
    _validate_submit(body, claims)
    params_hash = _parameters_hash(body)
    description = _description(body)
    nonce = body.caller_idempotency_key
    actor_sub = claims.sub

    async with rls_context_connection(
        RLSContext.platform_admin(
            source="http",
            audit_actor=f"bridge:{actor_sub}",
            user_id=actor_sub,
        )
    ) as conn:
        existing = await conn.fetchrow(
            """
            SELECT id, action_class, risk_tier, actor_sub, actor_type, description,
                   parameters_hash, status, requested_at, decided_by, decided_at,
                   expires_at
              FROM public.alpha_approval_queue
             WHERE nonce = $1 OR (actor_sub = $2 AND parameters_hash = $3)
             ORDER BY requested_at DESC
             LIMIT 1
            """,
            nonce,
            actor_sub,
            params_hash,
        )
        if existing is not None:
            return _row_to_response(existing)

        queue_id = await conn.fetchval(
            """
            SELECT public.enqueue_approval_request(
                $1::text[], $2::text, $3::text, $4::text, $5::text, $6::text, $7::text
            )
            """,
            ["financial_trade", "paper_trade"],
            body.tier_requested,
            actor_sub,
            "service",
            description,
            params_hash,
            nonce,
        )
        row = await conn.fetchrow(
            """
            SELECT id, action_class, risk_tier, actor_sub, actor_type, description,
                   parameters_hash, status, requested_at, decided_by, decided_at,
                   expires_at
              FROM public.alpha_approval_queue
             WHERE id = $1::uuid
            """,
            str(queue_id),
        )
    if row is None:
        raise HTTPException(status_code=500, detail="approval_queue_write_failed")
    logger.info("bridge_approval_submit queue_id=%s actor_sub=%s", row["id"], actor_sub)
    return _row_to_response(row)


@router.get("/approvals/{approval_id}", response_model=BridgeApprovalResponse)
async def get_bridge_approval(
    approval_id: UUID,
    claims: BridgeClaims = Depends(_require_financial_bridge_service),
) -> BridgeApprovalResponse:
    async with rls_context_connection(
        RLSContext.platform_admin(
            source="http",
            audit_actor=f"bridge:{claims.sub}",
            user_id=claims.sub,
        )
    ) as conn:
        row = await conn.fetchrow(
            """
            SELECT id, action_class, risk_tier, actor_sub, actor_type, description,
                   parameters_hash, status, requested_at, decided_by, decided_at,
                   expires_at
              FROM public.alpha_approval_queue
             WHERE id = $1::uuid
            """,
            str(approval_id),
        )
    if row is None:
        raise HTTPException(status_code=404, detail="approval_not_found")
    if row["actor_sub"] != claims.sub:
        raise HTTPException(status_code=404, detail="approval_not_found")
    return _row_to_response(row)


def _row_to_pending(row: Any) -> BridgePendingApproval:
    status = str(row["status"])
    mapped: BridgeStatus
    if status == "approved":
        mapped = "approved"
    elif status == "denied":
        mapped = "rejected"
    elif status == "expired":
        mapped = "expired"
    else:
        mapped = "pending"

    return BridgePendingApproval(
        approval_id=str(row["id"]),
        action_class=list(row["action_class"] or []),
        status=mapped,
        tier_assigned=str(row["risk_tier"]),
        actor_sub=str(row["actor_sub"]),
        actor_type=str(row["actor_type"]),
        description=str(row["description"]),
        requested_at=row["requested_at"],
        expires_at=row["expires_at"],
        overnight=bool(_row_get(row, "overnight", False)),
    )


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _validate_submit(body: BridgeApprovalSubmitRequest, claims: BridgeClaims) -> None:
    if body.domain != "jarvis-financial":
        raise HTTPException(status_code=400, detail="unsupported_domain")
    if body.service_caller != claims.sub:
        raise HTTPException(status_code=403, detail="service_caller_mismatch")
    if body.envelope_version != "1.0.0":
        raise HTTPException(status_code=400, detail="unsupported_envelope_version")


def _row_to_response(row: Any) -> BridgeApprovalResponse:
    status = str(row["status"])
    mapped: BridgeStatus
    if status == "approved":
        mapped = "approved"
    elif status == "denied":
        mapped = "rejected"
    elif status == "expired":
        mapped = "expired"
    else:
        mapped = "pending"

    intent_token = None
    intent_expires_at = None
    if mapped == "approved":
        intent_expires_at = row["expires_at"]
        intent_token = _intent_token(row)

    return BridgeApprovalResponse(
        approval_id=str(row["id"]),
        status=mapped,
        tier_assigned=str(row["risk_tier"]),
        intent_token=intent_token,
        intent_expires_at=intent_expires_at,
        decided_at=row["decided_at"],
        decided_by=row["decided_by"],
        rejection_reason="operator rejected" if mapped == "rejected" else None,
    )


def _intent_token(row: Any) -> str:
    expires_at = row["expires_at"]
    if expires_at is None:
        raise HTTPException(status_code=500, detail="approved_intent_missing_expiry")
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    claims = {
        "iss": "jarvis-alpha-bridge",
        "sub": "jarvis-alpha-bridge",
        "aud": "jarvis-financial",
        "iat": now,
        "exp": expires_at,
        "jti": str(uuid4()),
        "approval_id": str(row["id"]),
        "tier": row["risk_tier"],
        "intent_kind": "trade_proposal",
        "domain": "jarvis-financial",
    }
    return jwt.encode(claims, _alpha_private_key(), algorithm="RS256")


def _description(body: BridgeApprovalSubmitRequest) -> str:
    payload = body.payload
    symbol = payload.get("symbol", "UNKNOWN")
    side = payload.get("side", "unknown")
    qty = payload.get("qty", "?")
    notional = payload.get("est_value_usd", "?")
    return f"Financial paper trade proposal: {side} {qty} {symbol}, est ${notional}"


def _parameters_hash(body: BridgeApprovalSubmitRequest) -> str:
    canonical = json.dumps(
        {
            "domain": body.domain,
            "intent_kind": body.intent_kind,
            "tier": body.tier_requested,
            "payload": body.payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _financial_public_key() -> str:
    path = os.environ.get(
        "ALPHA_BRIDGE_FINANCIAL_PUBLIC_KEY_PATH",
        _DEFAULT_FINANCIAL_PUBLIC_KEY,
    )
    return Path(path).expanduser().read_text(encoding="utf-8")


def _alpha_private_key() -> str:
    path = os.environ.get("ALPHA_JWT_PRIVATE_KEY", _DEFAULT_ALPHA_PRIVATE_KEY)
    return Path(path).expanduser().read_text(encoding="utf-8")
