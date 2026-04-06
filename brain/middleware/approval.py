"""
Approval Gateway middleware — T1-T3 non-blocking flow.

Middleware stack position: CORS → Auth → RLS → Approval → RateLimit → handler

Phase 1 (this file):
- Classifies every request by action class
- Determines risk tier
- T1: execute, minimal log (no DB write)
- T2: execute, INSERT audit record
- T3: execute, INSERT audit record, mark for notification
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
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

# Paths that skip approval entirely (pre-auth paths already skipped by AuthMiddleware)
SKIP_PATHS = {"/v1/auth/pin", "/health"}


class ApprovalMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip OPTIONS (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)

        # Skip pre-auth paths
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        async def receive_body():
            body = b""
            while True:
                message = await request.receive()
                body += message.get("body", b"")
                if not message.get("more_body", False):
                    break
            return body

        body_bytes = await receive_body()
        parameters_hash = hashlib.sha256(body_bytes or b"").hexdigest()
        replay_sent = False

        async def new_receive():
            nonlocal replay_sent
            if replay_sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            replay_sent = True
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        replay_request = Request(request.scope, receive=new_receive)

        actor_sub = (
            getattr(request.state, "user_sub", None)
            or getattr(request.state, "user_id", None)
            or getattr(request.state, "sub", None)
            or "unknown"
        )
        actor_type = getattr(request.state, "actor_type", "user")

        approved_queue_id = await self._get_approved_queue_id(
            actor_sub=actor_sub,
            parameters_hash=parameters_hash,
        )
        if approved_queue_id:
            response = await call_next(replay_request)
            await self._consume_approved_queue(approved_queue_id)
            return response

        # Classify
        action_classes = classify_route(request.method, request.url.path)
        risk_tier = determine_risk_tier(action_classes)
        action_class_str = ",".join(action_classes)

        # Attach to request.state for downstream use
        replay_request.state.action_classes = action_classes
        replay_request.state.risk_tier = risk_tier

        # T1 — execute, no audit
        if risk_tier == "T1":
            return await call_next(replay_request)

        # T2 — execute + audit
        if risk_tier == "T2":
            response = await call_next(replay_request)
            # Fire-and-forget audit (don't block response)
            try:
                await self._write_audit(
                    replay_request, action_classes, risk_tier, "auto"
                )
            except Exception:
                logger.error(
                    "audit write failed for T2 request %s %s",
                    request.method,
                    request.url.path,
                    exc_info=True,
                )
            return response

        # T3 — execute + audit + mark for notification
        if risk_tier == "T3":
            response = await call_next(replay_request)
            try:
                await self._write_audit(
                    replay_request, action_classes, risk_tier, "auto", notify=True
                )
            except Exception:
                logger.error(
                    "audit write failed for T3 request %s %s",
                    request.method,
                    request.url.path,
                    exc_info=True,
                )
            return response

        # T4/T5/unclassified — BLOCK and queue for approval
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

        async with pool.acquire() as conn:
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
                """UPDATE alpha_approval_queue
                   SET status = 'executed',
                       executed_at = NOW()
                   WHERE id = $1""",
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
                async with conn.transaction():
                    queue_id = await conn.fetchval(
                        """INSERT INTO alpha_approval_queue
                           (action_class, risk_tier, actor_sub, actor_type, description,
                            parameters_hash, nonce, status, requested_at, expires_at)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', NOW(), NOW() + INTERVAL '10 minutes')
                           RETURNING id""",
                        action_classes,
                        tier,
                        actor_sub,
                        actor_type,
                        description,
                        parameters_hash,
                        nonce,
                    )
                    await conn.execute(
                        """INSERT INTO alpha_approval_audit
                           (approval_id, action_class, risk_tier, actor_sub, actor_type,
                            description, parameters_hash, nonce, decision, decided_by, overnight)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'auto', $4, false)""",
                        queue_id,
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

    async def _write_audit(
        self,
        request: Request,
        action_classes: list[str],
        risk_tier: str,
        decision: str,
        notify: bool = False,
    ) -> None:
        """Write an audit record for T2/T3 actions."""
        pool = get_pool()
        if not pool:
            logger.error("no DB pool available for audit write")
            return

        actor_sub = getattr(request.state, "sub", "unknown")
        actor_type = getattr(request.state, "actor_type", "unknown")
        nonce = uuid4().hex
        params_str = f"{request.method} {request.url.path}"
        params_hash = hashlib.sha256(params_str.encode()).hexdigest()

        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO alpha_approval_audit
                   (action_class, risk_tier, actor_sub, actor_type,
                    description, parameters_hash, nonce, decision, decided_by, overnight)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                action_classes,
                risk_tier,
                actor_sub,
                actor_type,
                f"{request.method} {request.url.path}",
                params_hash,
                nonce,
                decision,
                "system",
                False,
            )

        if notify:
            logger.info(
                "T3 notification pending: %s %s by %s",
                request.method,
                request.url.path,
                actor_sub,
            )
