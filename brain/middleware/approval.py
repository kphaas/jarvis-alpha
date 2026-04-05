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

        # Classify
        action_classes = classify_route(request.method, request.url.path)
        risk_tier = determine_risk_tier(action_classes)

        # Attach to request.state for downstream use
        request.state.action_classes = action_classes
        request.state.risk_tier = risk_tier

        # T1 — execute, no audit
        if risk_tier == "T1":
            return await call_next(request)

        # T2 — execute + audit
        if risk_tier == "T2":
            response = await call_next(request)
            # Fire-and-forget audit (don't block response)
            try:
                await self._write_audit(request, action_classes, risk_tier, "auto")
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
            response = await call_next(request)
            try:
                await self._write_audit(
                    request, action_classes, risk_tier, "auto", notify=True
                )
            except Exception:
                logger.error(
                    "audit write failed for T3 request %s %s",
                    request.method,
                    request.url.path,
                    exc_info=True,
                )
            return response

        # T4/T5/unclassified — BLOCK (placeholder for next session)
        # In Phase 2: T4 queues for approval, T5 queues for PIN
        # For now: return 403 so we catch unclassified routes immediately
        return JSONResponse(
            status_code=403,
            content={
                "error": "approval_required",
                "risk_tier": risk_tier,
                "action_classes": action_classes,
                "message": f"This action requires approval (tier {risk_tier}). "
                f"Approval gateway T4/T5 flow not yet implemented.",
            },
        )

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
