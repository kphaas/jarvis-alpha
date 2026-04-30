"""
RLS-aware database connection helper.

Canonical entry point for any route that queries RLS-protected tables.
Reads identity from request.state (set by JWTAuthMiddleware) and:
  1. Acquires a connection from the pool
  2. SETs ROLE jarvis_alpha_app (revokes BYPASSRLS)
  3. Sets canonical 'rls.*' session variables consumed by RLS policies
  4. Yields the connection
  5. RESETs ROLE on exit

Fail-closed: if request.state has no user_id, raises HTTPException(401).
This forces auth bugs to surface immediately rather than silently returning
zero rows via the '_none' sentinel.

Usage:
    from brain.db.rls import rls_connection

    @router.get("/v1/example")
    async def example(request: Request):
        async with rls_connection(request) as conn:
            rows = await conn.fetch("SELECT * FROM alpha_dream_sessions")
            return rows

Background services (buddy, watchdog, executor) MUST NOT use this helper.
They use SECURITY DEFINER functions instead — see step 7 of build order.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import HTTPException, Request

from brain.db.pool import get_pool
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")


@asynccontextmanager
async def rls_connection(request: Request):
    """Acquire a DB connection with RLS session variables set from JWT claims.

    Variables set:
        rls.user_id      — JWT sub claim (canonical user identity)
        rls.role         — 'platform_admin' if admin else 'user'
        rls.max_rating   — 'all_ages' / 'age_8_plus' / 'teen' / 'adult'
        rls.workspace_id — primary workspace from JWT claim

    Raises:
        HTTPException(401): if request.state has no user_id (auth failed
            or route was mistakenly called without auth)
    """
    # Read identity from request.state — set by JWTAuthMiddleware
    user_id = getattr(request.state, "user_id", None)

    # Fail-closed: no identity = no connection
    if not user_id or user_id == "unknown":
        logger.warning(
            "rls_connection: rejected request with no identity — path=%s",
            request.url.path,
        )
        raise HTTPException(status_code=401, detail="Authentication required")

    profile_role = getattr(request.state, "role", "child") or "child"
    max_rating = getattr(request.state, "max_rating", "all_ages") or "all_ages"
    workspace_id = getattr(request.state, "workspace_id", None) or ""

    if profile_role == "admin":
        jarvis_role = "platform_admin"
    elif profile_role == "child":
        jarvis_role = "child"
    else:
        jarvis_role = "user"

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("SET ROLE jarvis_alpha_app")
        try:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('rls.user_id', $1, true)", user_id
                )
                await conn.execute(
                    "SELECT set_config('rls.role', $1, true)", jarvis_role
                )
                await conn.execute(
                    "SELECT set_config('rls.max_rating', $1, true)", max_rating
                )
                await conn.execute(
                    "SELECT set_config('rls.workspace_id', $1, true)", workspace_id
                )
                yield conn
        finally:
            await conn.execute("RESET ROLE")
