import os
import time
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from jose import jwt, JWTError
from pydantic import BaseModel

from brain.db.pool import get_pool
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
async def unlock_approvals(req: UnlockRequest):
    """Validate PIN and issue a 5-minute approval token."""
    pool = get_pool()
    async with pool.acquire() as conn:
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

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, action_class, risk_tier, actor_sub, actor_type,
                      description, status, requested_at, expires_at, overnight
               FROM alpha_approval_queue
               WHERE status = 'pending'
                 AND expires_at > NOW()
               ORDER BY requested_at ASC"""
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

    # Fetch the queue item
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM alpha_approval_queue WHERE id = $1",
            queue_id,
        )

    if not row:
        raise HTTPException(status_code=404, detail="Queue item not found")

    if row["status"] != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Queue item already {row['status']}",
        )

    actor_sub = getattr(request.state, "user_id", "unknown")
    nonce = uuid4().hex

    # Update queue + write audit in a single transaction
    async with pool.acquire() as conn:
        async with conn.transaction():
            if req.decision == "approved":
                await conn.execute(
                    """UPDATE alpha_approval_queue
                       SET status = 'approved',
                           decided_by = $1,
                           decided_at = NOW(),
                           expires_at = NOW() + INTERVAL '10 minutes'
                       WHERE id = $2""",
                    actor_sub,
                    queue_id,
                )
            else:
                await conn.execute(
                    """UPDATE alpha_approval_queue
                       SET status = 'denied',
                           decided_by = $1,
                           decided_at = NOW()
                       WHERE id = $2""",
                    actor_sub,
                    queue_id,
                )

            await conn.execute(
                """INSERT INTO alpha_approval_audit
                   (approval_id, action_class, risk_tier, actor_sub, actor_type,
                    description, parameters_hash, nonce, decision, decided_by, overnight)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
                row["id"],
                row["action_class"],
                row["risk_tier"],
                actor_sub,
                "user",
                row["description"],
                row["parameters_hash"],
                nonce,
                req.decision,
                actor_sub,
                row["overnight"],
            )

    logger.info(
        "APPROVAL_DECIDE queue_id=%s decision=%s by=%s",
        queue_id,
        req.decision,
        actor_sub,
    )

    return {
        "queue_id": str(row["id"]),
        "decision": req.decision,
        "description": row["description"],
        "expires_at": (
            row["expires_at"].isoformat() if req.decision == "approved" else None
        ),
    }
