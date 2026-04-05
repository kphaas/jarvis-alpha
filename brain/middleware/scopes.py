"""
Scope enforcement for service identity.

Usage on routes:
    from brain.middleware.scopes import require_scopes

    @router.get("/v1/buddy/events")
    @require_scopes("buddy.events.write", "admin")
    async def get_buddy_events(request: Request):
        ...

Rules:
    - If caller has actor_type="user" and role="admin", all scopes pass (wildcard).
    - If caller has scopes=["*"], all scopes pass.
    - Otherwise, caller must have at least one of the required scopes.
    - If no scopes match, return 403 Forbidden.
    - Deny-by-default: undecorated routes allow any authenticated caller.
"""

from __future__ import annotations

import functools
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")


def require_scopes(*required: str) -> Callable:
    """Decorator that enforces scope-based access control on a route handler.

    Args:
        *required: One or more scope strings. Caller must have at least one.

    Examples:
        @require_scopes("dream.execute")
        @require_scopes("memory.evict", "memory.promote")
        @require_scopes("admin")  # only admin users
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Find the Request object in args or kwargs
            request = kwargs.get("request")
            if request is None:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if request is None:
                logger.error(
                    "SCOPE_CHECK_FAILED reason=no_request_object route=%s",
                    func.__name__,
                )
                return JSONResponse(
                    status_code=500,
                    content={"error": "Internal error: request not found"},
                )

            # Extract identity from request state (set by jwt_auth middleware)
            actor_type = getattr(request.state, "actor_type", "user")
            role = getattr(request.state, "role", None)
            caller_scopes = getattr(request.state, "scopes", [])
            iss = getattr(request.state, "iss", "unknown")

            # Admin users bypass scope checks
            if actor_type == "user" and role == "admin":
                return await func(*args, **kwargs)

            # Wildcard scope
            if "*" in caller_scopes:
                return await func(*args, **kwargs)

            # Check if caller has at least one required scope
            if set(required) & set(caller_scopes):
                return await func(*args, **kwargs)

            # Denied
            logger.warning(
                "SCOPE_DENIED iss=%s actor=%s required=%s has=%s route=%s",
                iss,
                actor_type,
                list(required),
                caller_scopes,
                func.__name__,
            )
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Forbidden",
                    "detail": f"Required scope(s): {', '.join(required)}",
                    "your_scopes": caller_scopes,
                },
            )

        return wrapper

    return decorator
