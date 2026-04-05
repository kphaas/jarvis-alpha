"""
RLS-aware database connection helper.

Usage in routes:
    from brain.db.rls import rls_connection

    async with rls_connection(request) as conn:
        rows = await conn.fetch("SELECT * FROM alpha_dream_sessions")
        # RLS policies will filter based on profile_id, role, max_rating
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Request

from brain.db.pool import get_pool


@asynccontextmanager
async def rls_connection(request: Request):
    """Acquire a DB connection with RLS session variables set from JWT claims.

    Sets:
        app.profile_id   — e.g. 'ken', 'ryleigh', 'sloane'
        app.profile_role  — 'admin' or 'child'
        app.max_rating    — 'all_ages', 'age_8_plus', 'teen', 'adult'
        app.user_id       — same as profile_id (backward compat)
    """
    pool = get_pool()
    profile_id = getattr(request.state, "sub", "_none") or "_none"
    profile_role = getattr(request.state, "role", "child") or "child"
    max_rating = getattr(request.state, "max_rating", "all_ages") or "all_ages"

    async with pool.acquire() as conn:
        await conn.execute("SET ROLE jarvis_alpha_app")
        await conn.execute("SELECT set_config('app.profile_id', $1, true)", profile_id)
        await conn.execute(
            "SELECT set_config('app.profile_role', $1, true)", profile_role
        )
        await conn.execute("SELECT set_config('app.max_rating', $1, true)", max_rating)
        await conn.execute("SELECT set_config('app.user_id', $1, true)", profile_id)
        try:
            yield conn
        finally:
            await conn.execute("RESET ROLE")
