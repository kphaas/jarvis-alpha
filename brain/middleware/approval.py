"""
Approval Gateway middleware — T1-T3 non-blocking flow.

Middleware stack position: CORS → Auth → RLS → Approval → RateLimit → handler

Phase 1 (this file):
- Classifies every request by action class
- Determines risk tier
- T1: execute, minimal log (no DB write)
- T2: execute, no DB audit (access logs only)
- T3: execute, log cost-incurring marker, no DB audit
- T4/T5: BLOCK with 403 + message "Approval required" (placeholder until next session)
- Unclassified: BLOCK with 403

Phase 2 (next session):
- T4: pause, queue, poll
- T5: pause, queue, PIN re-entry
"""

import hashlib
from uuid import uuid4

from asyncpg.exceptions import UniqueViolationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from brain.db.pool import get_pool
from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.services.approval_notifier import send_approval_notification
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

# Paths that skip approval entirely (pre-auth paths already skipped by AuthMiddleware)
SKIP_PATHS = {"/v1/auth/pin", "/health"}


class ApprovalMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        # Classify BEFORE reading body — no body needed for classification
        action_classes = classify_route(request.method, request.url.path)
        risk_tier = determine_risk_tier(action_classes)

        # T1 — pass through, no audit, no body read
        if risk_tier == "T1":
            request.state.action_classes = action_classes
            request.state.risk_tier = risk_tier
            return await call_next(request)

        # T2 — pass through, no audit (T2 is tracked via standard access logs)
        if risk_tier == "T2":
            request.state.action_classes = action_classes
            request.state.risk_tier = risk_tier
            return await call_next(request)

        # T3 — pass through + log notification marker (no DB audit)
        if risk_tier == "T3":
            request.state.action_classes = action_classes
            request.state.risk_tier = risk_tier
            response = await call_next(request)
            logger.info(
                "T3 cost-incurring request: %s %s",
                request.method,
                request.url.path,
            )
            return response

        # --- T4/T5 only below this line — safe to read body ---

        actor_sub = (
            getattr(request.state, "user_sub", None)
            or getattr(request.state, "user_id", None)
            or getattr(request.state, "sub", None)
            or "unknown"
        )
        actor_type = getattr(request.state, "actor_type", "user")

        # Read body for hash — only T4/T5 gets here
        body_bytes = await request.body()
        parameters_hash = hashlib.sha256(body_bytes or b"").hexdigest()

        # Check if this request was already approved
        approved_queue_id = await self._get_approved_queue_id(
            actor_sub=actor_sub,
            parameters_hash=parameters_hash,
        )
        if approved_queue_id:
            response = await call_next(request)
            await self._consume_approved_queue(approved_queue_id)
            return response

        # Queue for approval
        action_class_str = ",".join(action_classes)
        queue_id = await self._queue_for_approval(
            actor_sub=actor_sub,
            actor_type=actor_type,
            method=request.method,
            path=request.url.path,
            parameters_hash=parameters_hash,
            tier=risk_tier,
            action_classes=action_classes,
        )
        if not queue_id:
            return JSONResponse(
                status_code=500, content={"detail": "approval_queue_failed"}
            )

        # Notify — fire and forget
        try:
            await send_approval_notification(
                queue_id=queue_id,
                tier=risk_tier,
                action_classes=action_classes,
                method=request.method,
                path=request.url.path,
                actor_sub=actor_sub,
                actor_type=actor_type,
            )
        except Exception:
            logger.error("approval notification failed", exc_info=True)

        return JSONResponse(
            status_code=403,
            content={
                "detail": "approval_required",
                "queue_id": queue_id,
                "tier": risk_tier,
                "action_class": action_class_str,
            },
        )

    async def _get_approved_queue_id(
        self, actor_sub: str, parameters_hash: str
    ) -> str | None:
        pool = get_pool()
        if not pool:
            logger.error("no DB pool available for approval queue read")
            return None

        # System-level read: the approval-consumption path must always run as
        # platform_admin regardless of requester identity. rls_connection() is
        # request-scoped and derives role from JWT, which would only fix the
        # admin-actor case. See TD-211 / DISCOVERY_2026-05-11_td211_consume_approved.md.
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('rls.role', 'platform_admin', true)"
                )
                row = await conn.fetchrow(
                    """SELECT id
                       FROM alpha_approval_queue
                       WHERE actor_sub = $1
                         AND parameters_hash = $2
                         AND status = 'approved'
                         AND expires_at > NOW()
                       ORDER BY requested_at DESC
                       LIMIT 1""",
                    actor_sub,
                    parameters_hash,
                )

        return str(row["id"]) if row else None

    async def _consume_approved_queue(self, queue_id: str) -> None:
        pool = get_pool()
        if not pool:
            logger.error("no DB pool available for approval consume write")
            return

        async with pool.acquire() as conn:
            await conn.execute(
                "SELECT public.consume_approved_queue_item($1::uuid)",
                queue_id,
            )

    async def _queue_for_approval(
        self,
        actor_sub: str,
        actor_type: str,
        method: str,
        path: str,
        parameters_hash: str,
        tier: str,
        action_classes: list[str],
    ) -> str | None:
        pool = get_pool()
        if not pool:
            logger.error("no DB pool available for approval queue write")
            return None

        async with pool.acquire() as conn:
            nonce = uuid4().hex
            description = f"{method} {path}"
            try:
                queue_id = await conn.fetchval(
                    """SELECT public.enqueue_approval_request(
                           $1::text[], $2, $3, $4, $5, $6, $7
                       )""",
                    action_classes,
                    tier,
                    actor_sub,
                    actor_type,
                    description,
                    parameters_hash,
                    nonce,
                )
                return str(queue_id)
            except UniqueViolationError:
                existing = None
                async with conn.transaction():
                    await conn.execute(
                        "SELECT set_config('rls.role', 'platform_admin', true)"
                    )
                    existing = await conn.fetchval(
                        """SELECT id FROM alpha_approval_queue
                           WHERE actor_sub = $1
                             AND parameters_hash = $2
                             AND status = 'pending'
                           LIMIT 1""",
                        actor_sub,
                        parameters_hash,
                    )
                if existing:
                    return str(existing)
                return None
