"""
RLS-aware database connection helper.

Canonical entry point for any route that queries RLS-protected tables.
Reads identity from request.state (set by JWTAuthMiddleware) and:
  1. Acquires a connection from the pool
  2. SETs ROLE jarvis_alpha_app (revokes BYPASSRLS)
  3. Sets both 'app.*' and 'jarvis.*' session variables (split-brain RLS compat)
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

    Sets BOTH naming conventions because the schema has split-brain policies:
        - 'app.*'      — used by child_memory_rating, child_memory_write,
                          chat policies, task policies
        - 'jarvis.*'   — used by alpha_memory_isolation (legacy convention)

    Variables set:
        app.user_id        — JWT sub claim (canonical user identity)
        app.profile_id     — same as user_id (alias for backward compat)
        app.profile_role   — 'admin' or 'child'
        app.max_rating     — 'all_ages' / 'age_8_plus' / 'teen' / 'adult'
        app.workspace_id   — primary workspace from JWT claim
        jarvis.current_user — same as user_id (legacy alias)
        jarvis.role        — 'platform_admin' if admin else 'user'
        rls.user_id        — same as user_id (legacy alias for chat/watchdog)

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

    # Map app role to legacy jarvis.role naming
    jarvis_role = "platform_admin" if profile_role == "admin" else "user"

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("SET ROLE jarvis_alpha_app")
        # app.* convention (used by majority of policies)
        await conn.execute("SELECT set_config('app.user_id', $1, true)", user_id)
        await conn.execute("SELECT set_config('app.profile_id', $1, true)", user_id)
        await conn.execute(
            "SELECT set_config('app.profile_role', $1, true)", profile_role
        )
        await conn.execute("SELECT set_config('app.max_rating', $1, true)", max_rating)
        await conn.execute(
            "SELECT set_config('app.workspace_id', $1, true)", workspace_id
        )
        # jarvis.* convention (legacy — used by alpha_memory_isolation)
        await conn.execute(
            "SELECT set_config('jarvis.current_user', $1, true)", user_id
        )
        await conn.execute("SELECT set_config('jarvis.role', $1, true)", jarvis_role)
        # rls.* convention (legacy — used by chat policies, watchdog ingest)
        await conn.execute("SELECT set_config('rls.user_id', $1, true)", user_id)
        try:
            yield conn
        finally:
            await conn.execute("RESET ROLE")
