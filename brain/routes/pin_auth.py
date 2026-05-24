import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import bcrypt
from fastapi import APIRouter, HTTPException, Request
from jose import jwt
from pydantic import BaseModel

from brain.db.pool import get_pool
from brain.middleware.scopes import check_scopes
from jarvis_common.logging_config import get_logger
from jarvis_common.secrets import get_secret

logger = get_logger("alpha_brain")

router = APIRouter(prefix="/v1/auth", tags=["auth"])

_DEFAULT_KEY = "~/jarvis/pki/jwt/jwt_private.pem"


class PinRequest(BaseModel):
    pin: str
    profile_id: str = "ken"  # default to ken for backward compat


class SetChildPinRequest(BaseModel):
    profile_id: str
    new_pin: str


class SetProfilePinRequest(BaseModel):
    profile_id: str
    new_pin: str


class ProfileResponse(BaseModel):
    id: str
    display_name: str
    role: str
    child_age: int | None
    max_rating: str
    pin_status: Literal["set", "placeholder"]


def _pin_status(pin_hash: str) -> Literal["set", "placeholder"]:
    if pin_hash == "PLACEHOLDER_MIGRATE_FROM_ALPHA_PIN":
        try:
            get_secret("ALPHA_PIN")
        except KeyError:
            return "placeholder"
        return "set"
    if pin_hash.startswith("PLACEHOLDER"):
        return "placeholder"
    return "set"


def _validate_new_pin(new_pin: str) -> None:
    if len(new_pin) < 4:
        raise HTTPException(status_code=400, detail="PIN must be at least 4 characters")


def _hash_pin(new_pin: str) -> str:
    return bcrypt.hashpw(new_pin.encode("utf-8"), bcrypt.gensalt()).decode()


@router.post("/pin")
async def authenticate_pin(req: PinRequest):
    pool = get_pool()
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT * FROM alpha_profiles WHERE id = $1 AND active = true",
            req.profile_id,
        )

    if not profile:
        logger.warning("AUTH_FAIL reason=profile_not_found profile=%s", req.profile_id)
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if profile["pin_hash"] == "PLACEHOLDER_MIGRATE_FROM_ALPHA_PIN":
        try:
            alpha_pin = get_secret("ALPHA_PIN")
        except KeyError:
            raise HTTPException(
                status_code=500,
                detail="ALPHA_PIN not configured",
            )
        if req.pin != alpha_pin:
            logger.warning("AUTH_FAIL reason=bad_pin profile=%s", req.profile_id)
            raise HTTPException(status_code=401, detail="Invalid credentials")
    elif profile["pin_hash"].startswith("PLACEHOLDER"):
        logger.warning("AUTH_FAIL reason=pin_not_set profile=%s", req.profile_id)
        raise HTTPException(
            status_code=401,
            detail="PIN not configured. Ask admin to set PIN.",
        )
    else:
        if not bcrypt.checkpw(
            req.pin.encode("utf-8"),
            profile["pin_hash"].encode("utf-8"),
        ):
            logger.warning("AUTH_FAIL reason=bad_pin profile=%s", req.profile_id)
            raise HTTPException(status_code=401, detail="Invalid credentials")

    # Look up the user's primary workspace (single workspace today, defer multi-workspace)
    async with pool.acquire() as conn:
        workspace_row = await conn.fetchrow(
            """
            SELECT workspace_id
            FROM alpha_workspace_users
            WHERE user_id = $1
            ORDER BY created_at ASC
            LIMIT 1
            """,
            req.profile_id,
        )
    workspace_id = workspace_row["workspace_id"] if workspace_row else None

    key_path = os.environ.get("ALPHA_JWT_PRIVATE_KEY", _DEFAULT_KEY)
    pem_path = Path(key_path).expanduser()
    private_key = pem_path.read_text(encoding="utf-8")

    now = int(time.time())

    claims = {
        "sub": profile["id"],
        "iss": "user",
        "role": profile["role"],
        "profile_id": profile["id"],
        "workspace_id": workspace_id,
        "display_name": profile["display_name"],
        "actor_type": "user",
        "max_rating": profile["max_rating"],
        "scopes": ["*"]
        if profile["role"] == "admin"
        else ["ask", "chat.read", "health.read", "vault.read"],
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + (30 * 86400),  # 30 days
    }

    if profile["child_age"] is not None:
        claims["child_age"] = profile["child_age"]

    token = jwt.encode(claims, private_key, algorithm="RS256")
    expires_at = (
        datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return {"token": token, "expires_at": expires_at}


@router.get("/profiles", response_model=list[ProfileResponse])
async def list_profiles(request: Request):
    check_scopes(request, "admin")

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, display_name, role, child_age, max_rating, pin_hash
            FROM alpha_profiles
            WHERE active = true
            ORDER BY
                CASE WHEN role = 'admin' THEN 0 ELSE 1 END,
                CASE id
                    WHEN 'ken' THEN 0
                    WHEN 'sweta' THEN 1
                    WHEN 'ryleigh' THEN 2
                    WHEN 'sloane' THEN 3
                    ELSE 99
                END,
                display_name
            """
        )

    return [
        ProfileResponse(
            id=row["id"],
            display_name=row["display_name"],
            role=row["role"],
            child_age=row["child_age"],
            max_rating=row["max_rating"],
            pin_status=_pin_status(row["pin_hash"]),
        )
        for row in rows
    ]


@router.post("/set-child-pin")
async def set_child_pin(request: Request, req: SetChildPinRequest):
    check_scopes(request, "admin")
    _validate_new_pin(req.new_pin)

    pool = get_pool()
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT id, role FROM alpha_profiles WHERE id = $1", req.profile_id
        )
        if not profile or profile["role"] != "child":
            raise HTTPException(
                status_code=400, detail="Profile not found or not a child profile"
            )

        await conn.execute(
            "UPDATE alpha_profiles SET pin_hash = $1 WHERE id = $2",
            _hash_pin(req.new_pin),
            req.profile_id,
        )
    logger.info(
        "CHILD_PIN_SET profile=%s by=%s",
        req.profile_id,
        getattr(request.state, "iss", "unknown"),
    )
    return {"status": "ok", "profile_id": req.profile_id}


@router.post("/set-profile-pin")
async def set_profile_pin(request: Request, req: SetProfilePinRequest):
    check_scopes(request, "admin")
    _validate_new_pin(req.new_pin)

    if req.profile_id == "ken":
        raise HTTPException(
            status_code=400,
            detail="Use Change Admin PIN for Ken so the current PIN is verified",
        )

    pool = get_pool()
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT id, role FROM alpha_profiles WHERE id = $1 AND active = true",
            req.profile_id,
        )
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")

        await conn.execute(
            "UPDATE alpha_profiles SET pin_hash = $1 WHERE id = $2",
            _hash_pin(req.new_pin),
            req.profile_id,
        )

    logger.info(
        "PROFILE_PIN_SET profile=%s role=%s by=%s",
        req.profile_id,
        profile["role"],
        getattr(request.state, "iss", "unknown"),
    )
    return {"status": "ok", "profile_id": req.profile_id}


class SetAdminPinRequest(BaseModel):
    current_pin: str
    new_pin: str


@router.post("/set-admin-pin")
async def set_admin_pin(request: Request, req: SetAdminPinRequest):
    """Allow admin to update their own PIN. Requires valid current PIN."""
    pool = get_pool()
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT * FROM alpha_profiles WHERE id = 'ken' AND active = true"
        )

    if not profile:
        raise HTTPException(status_code=404, detail="Admin profile not found")

    # Verify current PIN
    if profile["pin_hash"] == "PLACEHOLDER_MIGRATE_FROM_ALPHA_PIN":
        try:
            alpha_pin = get_secret("ALPHA_PIN")
        except KeyError:
            raise HTTPException(status_code=500, detail="ALPHA_PIN not configured")
        if req.current_pin != alpha_pin:
            logger.warning("SET_ADMIN_PIN_FAIL reason=bad_current_pin")
            raise HTTPException(status_code=401, detail="Invalid current PIN")
    elif profile["pin_hash"].startswith("PLACEHOLDER"):
        raise HTTPException(status_code=401, detail="PIN not configured")
    else:
        if not bcrypt.checkpw(
            req.current_pin.encode("utf-8"),
            profile["pin_hash"].encode("utf-8"),
        ):
            logger.warning("SET_ADMIN_PIN_FAIL reason=bad_current_pin")
            raise HTTPException(status_code=401, detail="Invalid current PIN")

    _validate_new_pin(req.new_pin)

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE alpha_profiles SET pin_hash = $1 WHERE id = 'ken'",
            _hash_pin(req.new_pin),
        )

    logger.info("SET_ADMIN_PIN_SUCCESS profile=ken")
    return {"status": "ok", "profile_id": "ken"}
