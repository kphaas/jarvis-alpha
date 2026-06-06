import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from jose import jwt
from pydantic import BaseModel

from brain.db.rls import platform_admin_connection
from brain.middleware.jwt_auth import ALPHA_SESSION_COOKIE, require_auth
from brain.middleware.scopes import check_scopes
from brain.services.family_pin_sync import (
    FamilyPinSyncError,
    has_family_pin_target,
    sync_family_pin_hash,
)
from jarvis_common.logging_config import get_logger
from jarvis_common.secrets import get_secret

logger = get_logger("alpha_brain")

router = APIRouter(prefix="/v1/auth", tags=["auth"])

_DEFAULT_KEY = "~/jarvis/pki/jwt/jwt_private.pem"
_SESSION_COOKIE_SAMESITE: Literal["strict"] = "strict"


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


class LoginProfileResponse(BaseModel):
    id: str
    display_name: str
    role: str
    child_age: int | None
    max_rating: str


class SessionPrincipal(BaseModel):
    profile_id: str
    role: str
    actor_type: str
    workspace_id: str | None = None
    max_rating: str
    child_age: int | None = None


class SessionState(BaseModel):
    mode: Literal["alpha_session_cookie_or_bearer"] = "alpha_session_cookie_or_bearer"
    expires_at: str | None = None


class SessionApplicationGrant(BaseModel):
    status: Literal["authorized", "missing_scope"]
    required_scopes: list[str]
    granted_scopes: list[str]
    capabilities: list[str]


class SessionBrokerResponse(BaseModel):
    authority: Literal["jarvis-alpha"] = "jarvis-alpha"
    authenticated: Literal[True] = True
    session: SessionState
    principal: SessionPrincipal
    applications: dict[str, SessionApplicationGrant]


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


def _session_hours() -> int:
    try:
        return max(int(os.environ.get("ALPHA_SESSION_HOURS", "24")), 1)
    except ValueError:
        return 24


def _profile_scopes(role: str) -> list[str]:
    if role == "admin":
        return ["*"]
    if role == "child":
        return ["ask", "chat.read", "health.read"]
    return ["ask", "chat.read", "health.read", "vault.read"]


def _set_alpha_session_cookie(
    response: Response, token: str, max_age_seconds: int
) -> None:
    response.set_cookie(
        key=ALPHA_SESSION_COOKIE,
        value=token,
        max_age=max_age_seconds,
        path="/",
        secure=True,
        httponly=True,
        samesite=_SESSION_COOKIE_SAMESITE,
    )


def _session_cookie_max_age_seconds(request: Request) -> int:
    exp = getattr(request.state, "jwt_exp", None)
    if isinstance(exp, (int, float)):
        return max(int(exp) - int(time.time()), 1)
    return _session_hours() * 3600


def _session_expires_at(request: Request) -> str | None:
    exp = getattr(request.state, "jwt_exp", None)
    if not isinstance(exp, (int, float)):
        return None
    return (
        datetime.fromtimestamp(int(exp), tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _session_scopes(request: Request) -> list[str]:
    scopes = getattr(request.state, "scopes", [])
    if not isinstance(scopes, list):
        return []
    return [scope for scope in scopes if isinstance(scope, str)]


def _has_session_scope(request: Request, required_scope: str) -> bool:
    actor_type = str(getattr(request.state, "actor_type", "user"))
    role = str(getattr(request.state, "role", "user"))
    scopes = _session_scopes(request)
    return (
        (actor_type == "user" and role == "admin")
        or "*" in scopes
        or required_scope in scopes
    )


def _session_broker_response(request: Request) -> SessionBrokerResponse:
    profile_id = str(
        getattr(
            request.state,
            "profile_id",
            getattr(request.state, "user_id", "unknown"),
        )
    )
    helm_authorized = _has_session_scope(request, "helm.read")

    return SessionBrokerResponse(
        session=SessionState(expires_at=_session_expires_at(request)),
        principal=SessionPrincipal(
            profile_id=profile_id,
            role=str(getattr(request.state, "role", "user")),
            actor_type=str(getattr(request.state, "actor_type", "user")),
            workspace_id=getattr(request.state, "workspace_id", None),
            max_rating=str(getattr(request.state, "max_rating", "all_ages")),
            child_age=getattr(request.state, "child_age", None),
        ),
        applications={
            "helm": SessionApplicationGrant(
                status="authorized" if helm_authorized else "missing_scope",
                required_scopes=["helm.read"],
                granted_scopes=_session_scopes(request),
                capabilities=[
                    "alpha.summary.read",
                    "family.summary.read",
                    "helm.action.propose",
                ]
                if helm_authorized
                else [],
            ),
            "family": SessionApplicationGrant(
                status="authorized" if helm_authorized else "missing_scope",
                required_scopes=["helm.read"],
                granted_scopes=_session_scopes(request),
                capabilities=["family.summary.read"] if helm_authorized else [],
            ),
        },
    )


FamilyPinSyncStatus = Literal["ok", "failed", "not_applicable"]


async def _sync_family_pin_status(
    profile_id: str, pin_hash: str
) -> FamilyPinSyncStatus:
    if not has_family_pin_target(profile_id):
        return "not_applicable"

    try:
        await sync_family_pin_hash(profile_id, pin_hash)
    except FamilyPinSyncError:
        logger.warning(
            "FAMILY_PIN_SYNC_DEGRADED profile=%s",
            profile_id,
            exc_info=True,
        )
        return "failed"
    return "ok"


_PROFILE_SELECT_SQL = """
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


@router.post("/pin")
async def authenticate_pin(req: PinRequest, response: Response):
    async with platform_admin_connection(source="http", audit_actor="auth_pin") as conn:
        profile = await conn.fetchrow(
            "SELECT * FROM alpha_profiles WHERE id = $1 AND active = true",
            req.profile_id,
        )
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
        "scopes": _profile_scopes(profile["role"]),
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + (_session_hours() * 3600),
    }

    if profile["child_age"] is not None:
        claims["child_age"] = profile["child_age"]

    token = jwt.encode(claims, private_key, algorithm="RS256")
    _set_alpha_session_cookie(
        response,
        token,
        max_age_seconds=max(claims["exp"] - now, 1),
    )
    expires_at = (
        datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    return {"token": token, "expires_at": expires_at}


@router.post("/session-cookie")
async def refresh_session_cookie(request: Request, response: Response):
    token = getattr(request.state, "jwt_token", None)
    if not isinstance(token, str) or not token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    _set_alpha_session_cookie(
        response,
        token,
        max_age_seconds=_session_cookie_max_age_seconds(request),
    )
    return {"status": "ok"}


@router.get("/session", response_model=SessionBrokerResponse)
async def current_session(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> SessionBrokerResponse:
    """Return the current Alpha session broker state without exposing tokens."""
    return _session_broker_response(request)


@router.get("/login-profiles", response_model=list[LoginProfileResponse])
async def list_login_profiles():
    async with platform_admin_connection(
        source="http", audit_actor="auth_login_profiles"
    ) as conn:
        rows = await conn.fetch(_PROFILE_SELECT_SQL)

    return [
        LoginProfileResponse(
            id=row["id"],
            display_name=row["display_name"],
            role=row["role"],
            child_age=row["child_age"],
            max_rating=row["max_rating"],
        )
        for row in rows
    ]


@router.get("/profiles", response_model=list[ProfileResponse])
async def list_profiles(request: Request):
    check_scopes(request, "admin")

    async with platform_admin_connection(
        source="http", audit_actor="auth_profiles_admin"
    ) as conn:
        rows = await conn.fetch(_PROFILE_SELECT_SQL)

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
    pin_hash = _hash_pin(req.new_pin)

    async with platform_admin_connection(
        source="http", audit_actor="auth_set_child_pin"
    ) as conn:
        profile = await conn.fetchrow(
            "SELECT id, role FROM alpha_profiles WHERE id = $1", req.profile_id
        )
        if not profile or profile["role"] != "child":
            raise HTTPException(
                status_code=400, detail="Profile not found or not a child profile"
            )

        await conn.execute(
            "UPDATE alpha_profiles SET pin_hash = $1 WHERE id = $2",
            pin_hash,
            req.profile_id,
        )

    family_sync_status = await _sync_family_pin_status(req.profile_id, pin_hash)
    logger.info(
        "CHILD_PIN_SET profile=%s family_sync_status=%s by=%s",
        req.profile_id,
        family_sync_status,
        getattr(request.state, "iss", "unknown"),
    )
    return {
        "status": "ok",
        "profile_id": req.profile_id,
        "family_sync_status": family_sync_status,
    }


@router.post("/set-profile-pin")
async def set_profile_pin(request: Request, req: SetProfilePinRequest):
    check_scopes(request, "admin")
    _validate_new_pin(req.new_pin)

    if req.profile_id == "ken":
        raise HTTPException(
            status_code=400,
            detail="Use Change Admin PIN for Ken so the current PIN is verified",
        )
    pin_hash = _hash_pin(req.new_pin)

    async with platform_admin_connection(
        source="http", audit_actor="auth_set_profile_pin"
    ) as conn:
        profile = await conn.fetchrow(
            "SELECT id, role FROM alpha_profiles WHERE id = $1 AND active = true",
            req.profile_id,
        )
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")

        await conn.execute(
            "UPDATE alpha_profiles SET pin_hash = $1 WHERE id = $2",
            pin_hash,
            req.profile_id,
        )

    family_sync_status = await _sync_family_pin_status(req.profile_id, pin_hash)
    logger.info(
        "PROFILE_PIN_SET profile=%s role=%s family_sync_status=%s by=%s",
        req.profile_id,
        profile["role"],
        family_sync_status,
        getattr(request.state, "iss", "unknown"),
    )
    return {
        "status": "ok",
        "profile_id": req.profile_id,
        "family_sync_status": family_sync_status,
    }


class SetAdminPinRequest(BaseModel):
    current_pin: str
    new_pin: str


@router.post("/set-admin-pin")
async def set_admin_pin(request: Request, req: SetAdminPinRequest):
    """Allow admin to update their own PIN. Requires valid current PIN."""
    async with platform_admin_connection(
        source="http", audit_actor="auth_set_admin_pin"
    ) as conn:
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
    pin_hash = _hash_pin(req.new_pin)

    async with platform_admin_connection(
        source="http", audit_actor="auth_set_admin_pin"
    ) as conn:
        await conn.execute(
            "UPDATE alpha_profiles SET pin_hash = $1 WHERE id = 'ken'",
            pin_hash,
        )

    family_sync_status = await _sync_family_pin_status("ken", pin_hash)
    logger.info(
        "SET_ADMIN_PIN_SUCCESS profile=ken family_sync_status=%s",
        family_sync_status,
    )
    return {
        "status": "ok",
        "profile_id": "ken",
        "family_sync_status": family_sync_status,
    }
