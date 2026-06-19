import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from jose import jwt, JWTError
from pydantic import BaseModel

from brain.agents.privacy_scrub.drafts import record_privacy_approval_decision
from brain.db.rls import rls_connection
from brain.middleware.scopes import check_scopes
from jarvis_common.logging_config import get_logger
from jarvis_common.secrets import get_secret

logger = get_logger("alpha_brain")

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])

_DEFAULT_KEY = "~/jarvis/pki/jwt/jwt_private.pem"
_DEFAULT_PUB_KEY = "~/jarvis-alpha/brain/pki/jwt_public.pem"
_APPROVAL_TOKEN_TTL = 300  # 5 minutes


# --- Models ---


class UnlockRequest(BaseModel):
    pin: str


class DecideRequest(BaseModel):
    decision: str  # "approved" or "denied"


# --- PIN unlock → short-lived approval token ---


@router.post("/unlock")
async def unlock_approvals(req: UnlockRequest, request: Request):
    """Validate PIN and issue a 5-minute approval token."""
    check_scopes(request, "admin")

    async with rls_connection(request) as conn:
        profile = await conn.fetchrow(
            "SELECT * FROM alpha_profiles WHERE id = 'ken' AND active = true"
        )

    if not profile:
        raise HTTPException(status_code=401, detail="Profile not found")

    # Validate PIN — same logic as pin_auth.py
    if profile["pin_hash"] == "PLACEHOLDER_MIGRATE_FROM_ALPHA_PIN":
        try:
            alpha_pin = get_secret("ALPHA_PIN")
        except KeyError:
            raise HTTPException(status_code=500, detail="ALPHA_PIN not configured")
        if req.pin != alpha_pin:
            logger.warning("APPROVAL_UNLOCK_FAIL reason=bad_pin")
            raise HTTPException(status_code=401, detail="Invalid PIN")
    elif profile["pin_hash"].startswith("PLACEHOLDER"):
        raise HTTPException(status_code=401, detail="PIN not configured")
    else:
        import bcrypt

        if not bcrypt.checkpw(
            req.pin.encode("utf-8"),
            profile["pin_hash"].encode("utf-8"),
        ):
            logger.warning("APPROVAL_UNLOCK_FAIL reason=bad_pin")
            raise HTTPException(status_code=401, detail="Invalid PIN")

    # Issue short-lived approval token
    key_path = os.environ.get("ALPHA_JWT_PRIVATE_KEY", _DEFAULT_KEY)
    private_key = Path(key_path).expanduser().read_text(encoding="utf-8")

    now = int(time.time())
    claims = {
        "sub": "ken",
        "purpose": "approval",
        "jti": str(uuid4()),
        "iat": now,
        "exp": now + _APPROVAL_TOKEN_TTL,
    }
    token = jwt.encode(claims, private_key, algorithm="RS256")

    logger.info("APPROVAL_UNLOCK ok — 5-min window started")
    return {"approval_token": token, "expires_in": _APPROVAL_TOKEN_TTL}


# --- List pending approvals ---


@router.get("/pending")
async def list_pending(request: Request):
    """List all pending approval queue items."""
    check_scopes(request, "admin")

    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            """
            WITH privacy_context AS (
                SELECT
                    approval_queue_id,
                    (ARRAY_AGG(DISTINCT case_draft_id))[1] AS case_draft_id,
                    COUNT(id)::INTEGER AS action_count,
                    ARRAY_REMOVE(
                        ARRAY_AGG(DISTINCT status ORDER BY status),
                        NULL
                    ) AS action_statuses
                FROM public.alpha_privacy_actions
                WHERE approval_queue_id IS NOT NULL
                GROUP BY approval_queue_id
            ),
            spark_context AS (
                SELECT
                    ranked.approval_queue_id,
                    ranked.principal_id AS spark_principal_id,
                    ranked.target_label AS spark_target_label,
                    ranked.id AS spark_outbox_id,
                    ranked.status AS spark_outbox_status
                FROM (
                    SELECT
                        o.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY o.approval_queue_id
                            ORDER BY o.created_at DESC, o.id DESC
                        ) AS row_rank
                    FROM public.alpha_spark_outbox AS o
                ) AS ranked
                WHERE ranked.row_rank = 1
            ),
            beacon_context AS (
                SELECT
                    ranked.approval_queue_id,
                    ranked.request_id AS beacon_request_id,
                    ranked.selected_tool AS beacon_selected_tool,
                    ranked.sensitivity AS beacon_sensitivity,
                    ranked.policy_tier AS beacon_policy_tier,
                    ranked.request_shape AS beacon_request_shape,
                    ranked.metadata AS beacon_metadata
                FROM (
                    SELECT
                        (event.metadata->>'approval_queue_id')::uuid
                            AS approval_queue_id,
                        request.id AS request_id,
                        request.selected_tool,
                        request.sensitivity,
                        request.policy_tier,
                        request.request_shape,
                        event.metadata,
                        ROW_NUMBER() OVER (
                            PARTITION BY event.metadata->>'approval_queue_id'
                            ORDER BY event.created_at DESC, event.id DESC
                        ) AS row_rank
                    FROM public.alpha_internet_tool_events AS event
                    JOIN public.alpha_internet_requests AS request
                      ON request.id = event.request_id
                    WHERE event.tool = 'browser_use'
                      AND event.event_type = 'approval_request'
                      AND event.metadata ? 'approval_queue_id'
                ) AS ranked
                WHERE ranked.row_rank = 1
            )
            SELECT q.id, q.action_class, q.risk_tier, q.actor_sub, q.actor_type,
                   q.description, q.parameters_hash, q.status,
                   q.requested_at, q.expires_at,
                   q.overnight, pc.case_draft_id AS privacy_case_id,
                   pc.action_count AS privacy_action_count,
                   pc.action_statuses AS privacy_action_statuses,
                   sc.spark_principal_id,
                   sc.spark_target_label,
                   sc.spark_outbox_id,
                   sc.spark_outbox_status,
                   bc.beacon_request_id,
                   bc.beacon_selected_tool,
                   bc.beacon_sensitivity,
                   bc.beacon_policy_tier,
                   bc.beacon_request_shape,
                   bc.beacon_metadata
            FROM public.alpha_approval_queue q
            LEFT JOIN privacy_context pc
              ON pc.approval_queue_id = q.id
            LEFT JOIN spark_context sc
              ON sc.approval_queue_id = q.id
            LEFT JOIN beacon_context bc
              ON bc.approval_queue_id = q.id
            WHERE q.status = 'pending'
              AND q.expires_at > NOW()
            ORDER BY q.requested_at ASC
            """
        )

    items = []
    for r in rows:
        items.append(
            {
                "id": str(r["id"]),
                "action_class": r["action_class"],
                "risk_tier": r["risk_tier"],
                "actor_sub": r["actor_sub"],
                "actor_type": r["actor_type"],
                "description": r["description"],
                "status": r["status"],
                "requested_at": r["requested_at"].isoformat()
                if r["requested_at"]
                else None,
                "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
                "overnight": r["overnight"],
                "privacy": _privacy_context_out(r),
                "spark": _spark_context_out(r),
                "beacon": _beacon_context_out(r),
            }
        )

    return {"pending": items, "count": len(items)}


# --- Decide (approve/deny) ---


@router.post("/{queue_id}/decide")
async def decide_approval(queue_id: str, req: DecideRequest, request: Request):
    """Approve or deny a queued T4/T5 action. Requires X-Approval-Token header."""
    check_scopes(request, "admin")

    if req.decision not in ("approved", "denied"):
        raise HTTPException(
            status_code=400, detail="decision must be 'approved' or 'denied'"
        )

    # Validate approval token from header
    approval_token = request.headers.get("x-approval-token")
    if not approval_token:
        raise HTTPException(status_code=403, detail="X-Approval-Token header required")

    pub_path = os.environ.get("ALPHA_JWT_PUBLIC_KEY", _DEFAULT_PUB_KEY)
    public_key = Path(pub_path).expanduser().read_text(encoding="utf-8")

    try:
        payload = jwt.decode(approval_token, public_key, algorithms=["RS256"])
    except JWTError:
        raise HTTPException(status_code=403, detail="Invalid or expired approval token")

    if payload.get("purpose") != "approval":
        raise HTTPException(status_code=403, detail="Token is not an approval token")

    actor_sub = getattr(request.state, "user_id", "unknown")
    nonce = uuid4().hex

    try:
        async with rls_connection(request) as conn:
            async with conn.transaction():
                rows = await conn.fetch(
                    "SELECT * FROM public.decide_approval($1::uuid, $2, $3, $4)",
                    queue_id,
                    req.decision,
                    actor_sub,
                    nonce,
                )
                row = rows[0] if rows else None
                if row and "privacy_draft_handoff" in (row["action_class"] or []):
                    await record_privacy_approval_decision(
                        conn,
                        approval_queue_id=UUID(queue_id),
                        decision=req.decision,
                        actor=actor_sub,
                    )
    except Exception as e:
        err = str(e)
        if "APPROVAL_NOT_FOUND" in err:
            raise HTTPException(status_code=404, detail="Queue item not found")
        if "APPROVAL_ALREADY_DECIDED" in err:
            raise HTTPException(status_code=409, detail="Queue item already decided")
        raise

    row = rows[0] if rows else None
    if not row:
        raise HTTPException(status_code=500, detail="decide_approval returned no rows")

    logger.info(
        "APPROVAL_DECIDE queue_id=%s decision=%s by=%s",
        queue_id,
        req.decision,
        actor_sub,
    )

    return {
        "queue_id": str(row["queue_id"]),
        "decision": req.decision,
        "description": row["description"],
        "expires_at": (
            row["expires_at"].isoformat() if req.decision == "approved" else None
        ),
    }


def _privacy_context_out(row) -> dict[str, object] | None:
    case_id = row["privacy_case_id"]
    if not case_id:
        return None
    return {
        "case_id": str(case_id),
        "action_count": int(row["privacy_action_count"] or 0),
        "action_statuses": list(row["privacy_action_statuses"] or []),
    }


def _spark_context_out(row) -> dict[str, object] | None:
    action_class = row["action_class"] or []
    if "spark_draft_handoff" not in action_class:
        return None
    return {
        "kind": "imessage_draft",
        "can_send": False,
        "requires_human_approval": True,
        "principal_id": row["spark_principal_id"],
        "target_label": row["spark_target_label"],
        "outbox_id": str(row["spark_outbox_id"]) if row["spark_outbox_id"] else None,
        "outbox_status": row["spark_outbox_status"],
        "outbox_recorded": bool(row["spark_outbox_id"]),
    }


def _beacon_context_out(row) -> dict[str, object] | None:
    action_class = _row_value(row, "action_class", []) or []
    request_id = _row_value(row, "beacon_request_id")
    if "beacon_browser_use" not in action_class and request_id is None:
        return None

    metadata = _json_object(_row_value(row, "beacon_metadata"))
    request_shape = _json_object(_row_value(row, "beacon_request_shape"))
    preview = _json_object(metadata.get("browser_action_preview"))
    parameters_hash = str(_row_value(row, "parameters_hash", "") or "")
    approval_hash_prefix = str(
        preview.get("approval_hash_prefix")
        or metadata.get("approval_hash_prefix")
        or _hash_prefix(parameters_hash)
    )

    return {
        "kind": "beacon_browser_use",
        "request_id": str(request_id) if request_id else None,
        "selected_tool": _safe_str(
            preview.get("selected_tool"),
            _row_value(row, "beacon_selected_tool", "browser_use"),
        ),
        "risk_tier": _safe_str(
            preview.get("risk_tier"),
            _row_value(row, "beacon_policy_tier", row["risk_tier"]),
        ),
        "sensitivity": _safe_str(
            preview.get("sensitivity"),
            _row_value(row, "beacon_sensitivity", "normal"),
        ),
        "requires_human_approval": True,
        "has_query": _safe_bool(
            preview.get("has_query"), request_shape.get("has_query")
        ),
        "url_count": _safe_int(
            preview.get("url_count"), request_shape.get("url_count")
        ),
        "max_pages": _safe_int(
            preview.get("max_pages"), request_shape.get("max_pages")
        ),
        "max_depth": _safe_int(
            preview.get("max_depth"), request_shape.get("max_depth")
        ),
        "needs_interaction": _safe_bool(
            preview.get("needs_interaction"),
            request_shape.get("needs_interaction"),
        ),
        "same_host_required": _safe_bool(preview.get("same_host_required"), True),
        "screenshots_required": _safe_bool(preview.get("screenshots_required"), True),
        "downloads_allowed": _safe_bool(preview.get("downloads_allowed"), False),
        "forms_allowed": _safe_bool(preview.get("forms_allowed"), False),
        "raw_task_text_included": False,
        "raw_web_content_is_untrusted": True,
        "approval_hash_prefix": approval_hash_prefix[:12],
    }


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _safe_str(value: object, fallback: object = "") -> str:
    if isinstance(value, str) and value:
        return value
    if isinstance(fallback, str):
        return fallback
    return str(fallback) if fallback is not None else ""


def _safe_int(value: object, fallback: object = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(fallback, bool):
        return int(fallback)
    if isinstance(fallback, int):
        return fallback
    return 0


def _safe_bool(value: object, fallback: object = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(fallback, bool):
        return fallback
    return False


def _hash_prefix(parameters_hash: str) -> str:
    clean = parameters_hash.split(":", 1)[-1]
    return clean[:12]
