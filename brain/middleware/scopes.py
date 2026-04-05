"""
Scope enforcement for service identity.

Usage:
    from brain.middleware.scopes import check_scopes

    async def create_session(request: Request, req: CreateSessionRequest):
        check_scopes(request, "dream.execute")
        ...

Rules:
    - User with role=admin bypasses all scope checks.
    - Caller with scopes=["*"] bypasses all scope checks.
    - Otherwise, caller must have at least one of the required scopes.
    - Raises HTTPException(403) if denied.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")


def check_scopes(request: Request, *required: str) -> None:
    """Check that the caller has at least one of the required scopes.

    Raises HTTPException(403) if denied. No-op for admin users.

    Args:
        request: The FastAPI Request object (must have state set by jwt_auth).
        *required: One or more scope strings. Caller must have at least one.
    """
    actor_type = getattr(request.state, "actor_type", "user")
    role = getattr(request.state, "role", None)
    caller_scopes = getattr(request.state, "scopes", [])
    iss = getattr(request.state, "iss", "unknown")

    # Admin users bypass scope checks
    if actor_type == "user" and role == "admin":
        return

    # Wildcard scope
    if "*" in caller_scopes:
        return

    # Check if caller has at least one required scope
    if set(required) & set(caller_scopes):
        return

    # Denied
    logger.warning(
        "SCOPE_DENIED iss=%s actor=%s required=%s has=%s",
        iss,
        actor_type,
        list(required),
        caller_scopes,
    )
    raise HTTPException(
        status_code=403,
        detail={
            "error": "Forbidden",
            "required_scopes": list(required),
            "your_scopes": caller_scopes,
        },
    )
