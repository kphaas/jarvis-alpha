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
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, Request

from brain.db.pool import get_pool
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

Role = Literal["platform_admin", "user", "child"]
MaxRating = Literal["all_ages", "age_8_plus", "teen", "adult"]
RLSContextSource = Literal[
    "http",
    "scheduled",
    "buddy",
    "dream",
    "executor",
    "watchdog",
    "test",
]


@dataclass(frozen=True, slots=True)
class RLSContext:
    """Immutable RLS context applied to a transaction-local DB session."""

    user_id: str
    role: Role
    max_rating: MaxRating
    workspace_id: str
    source: RLSContextSource
    audit_actor: str

    @classmethod
    def from_request(cls, request: Request) -> "RLSContext":
        user_id = getattr(request.state, "user_id", None)
        if not user_id or user_id == "unknown":
            logger.warning(
                "RLSContext.from_request: rejected request with no identity — path=%s",
                request.url.path,
            )
            raise HTTPException(status_code=401, detail="Authentication required")

        profile_role = getattr(request.state, "role", "child") or "child"
        if profile_role == "admin":
            jarvis_role: Role = "platform_admin"
        elif profile_role == "child":
            jarvis_role = "child"
        else:
            jarvis_role = "user"

        return cls(
            user_id=str(user_id),
            role=jarvis_role,
            max_rating=getattr(request.state, "max_rating", "all_ages") or "all_ages",
            workspace_id=getattr(request.state, "workspace_id", None) or "",
            source="http",
            audit_actor=str(
                getattr(request.state, "user_sub", None)
                or getattr(request.state, "user_id", None)
                or user_id
            ),
        )

    @classmethod
    def platform_admin(
        cls,
        *,
        source: RLSContextSource,
        audit_actor: str,
        user_id: str = "system",
        workspace_id: str = "",
    ) -> "RLSContext":
        return cls(
            user_id=user_id,
            role="platform_admin",
            max_rating="adult",
            workspace_id=workspace_id,
            source=source,
            audit_actor=audit_actor,
        )


async def set_rls_context(conn, ctx: RLSContext) -> None:
    """Set canonical rls.* GUCs for the current transaction.

    The variables are transaction-local via set_config(..., true). Callers must
    enter a transaction before invoking this helper.
    """
    in_transaction = getattr(conn, "is_in_transaction", None)
    if callable(in_transaction) and not in_transaction():
        raise RuntimeError("set_rls_context() must be called inside a transaction")

    await conn.execute(
        """
        SELECT
            set_config('rls.user_id', $1, true),
            set_config('rls.role', $2, true),
            set_config('rls.max_rating', $3, true),
            set_config('rls.workspace_id', $4, true),
            set_config('rls.source', $5, true),
            set_config('rls.audit_actor', $6, true)
        """,
        ctx.user_id,
        ctx.role,
        ctx.max_rating,
        ctx.workspace_id,
        ctx.source,
        ctx.audit_actor,
    )


@asynccontextmanager
async def rls_context_connection(
    ctx: RLSContext,
    *,
    pool=None,
    set_app_role: bool = False,
):
    """Acquire a connection and apply an explicit RLSContext."""
    pool = pool or get_pool()
    async with pool.acquire() as conn:
        if set_app_role:
            await conn.execute("SET ROLE jarvis_alpha_app")
        try:
            async with conn.transaction():
                await set_rls_context(conn, ctx)
                yield conn
        finally:
            if set_app_role:
                await conn.execute("RESET ROLE")


@asynccontextmanager
async def platform_admin_connection(
    *,
    source: RLSContextSource,
    audit_actor: str,
    pool=None,
):
    """Acquire a platform-admin RLS context for service-owned DB work."""
    ctx = RLSContext.platform_admin(source=source, audit_actor=audit_actor)
    async with rls_context_connection(ctx, pool=pool, set_app_role=False) as conn:
        yield conn


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
    ctx = RLSContext.from_request(request)

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("SET ROLE jarvis_alpha_app")
        try:
            async with conn.transaction():
                await set_rls_context(conn, ctx)
                yield conn
        finally:
            await conn.execute("RESET ROLE")
