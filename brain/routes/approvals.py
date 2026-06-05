import os
import time
from pathlib import Path
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
            )
            SELECT q.id, q.action_class, q.risk_tier, q.actor_sub, q.actor_type,
                   q.description, q.status, q.requested_at, q.expires_at,
                   q.overnight, pc.case_draft_id AS privacy_case_id,
                   pc.action_count AS privacy_action_count,
                   pc.action_statuses AS privacy_action_statuses
            FROM public.alpha_approval_queue q
            LEFT JOIN privacy_context pc
              ON pc.approval_queue_id = q.id
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
