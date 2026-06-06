"""Beacon internet evidence routes."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from brain.db.rls import rls_connection
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.services.internet_scout.browser_approvals import (
    enqueue_browser_task_approval,
)
from brain.services.internet_scout.executor import InternetScoutExecutor
from brain.services.internet_scout.models import (
    InternetScoutBrowserApprovalResponse,
    InternetScoutRequest,
    InternetScoutStoredResponse,
    InternetTool,
)
from brain.services.internet_scout.orchestrator import InternetScoutOrchestrator
from brain.services.internet_scout.repository import InternetScoutRepository
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")
router = APIRouter(prefix="/v1/internet-scout", tags=["internet-scout"])


@router.post("/research", response_model=InternetScoutStoredResponse)
async def internet_scout_research(
    body: InternetScoutRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutStoredResponse:
    """Run a P2 Beacon search/fetch request and store structured evidence."""
    check_scopes(request, "internet_scout.research", "admin")
    actor = str(getattr(request.state, "user_id", "unknown"))
    plan = InternetScoutOrchestrator().plan(body)

    async with rls_connection(request) as conn:
        repo = InternetScoutRepository(conn)
        request_id = await repo.create_request(
            user_id=actor,
            request=body,
            decision=plan.decision,
        )
        if not plan.decision.allowed:
            await repo.record_tool_event(
                request_id=request_id,
                tool=plan.decision.tool.value,
                event_type="policy",
                status="blocked",
                metadata={"blocked_reasons": plan.decision.blocked_reasons},
            )

    if not plan.decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "beacon_policy_denied",
                "request_id": str(request_id),
                "decision": plan.decision.model_dump(mode="json"),
            },
        )

    try:
        async with rls_connection(request) as conn:
            await InternetScoutRepository(conn).record_tool_event(
                request_id=request_id,
                tool=plan.decision.tool.value,
                event_type="gateway_call",
                status="started",
            )

        _decision, packet = await InternetScoutExecutor().execute(body)

        async with rls_connection(request) as conn:
            repo = InternetScoutRepository(conn)
            await repo.store_packet(request_id=request_id, packet=packet)
            await repo.record_tool_event(
                request_id=request_id,
                tool=plan.decision.tool.value,
                event_type="gateway_call",
                status="succeeded",
                metadata={
                    "source_count": len(packet.sources),
                    "claim_count": len(packet.claims),
                },
            )
            await repo.mark_request_succeeded(request_id)
    except Exception as exc:
        async with rls_connection(request) as conn:
            repo = InternetScoutRepository(conn)
            await repo.record_tool_event(
                request_id=request_id,
                tool=plan.decision.tool.value,
                event_type="gateway_call",
                status="failed",
                error_text=str(exc),
            )
            await repo.mark_request_failed(request_id, str(exc))
        logger.warning(
            "BEACON_RESEARCH_FAIL request_id=%s tool=%s",
            request_id,
            plan.decision.tool.value,
        )
        raise

    return InternetScoutStoredResponse(
        request_id=request_id,
        plan=plan,
        evidence=packet,
    )


@router.post(
    "/browser-task/approval-request",
    response_model=InternetScoutBrowserApprovalResponse,
)
async def internet_scout_browser_approval_request(
    body: InternetScoutRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutBrowserApprovalResponse:
    """Queue browser-use work for approval; do not execute browser automation."""
    check_scopes(request, "internet_scout.research", "admin")
    if not body.query and not body.urls:
        raise HTTPException(status_code=400, detail="browser_use_task_required")
    browser_body = body.model_copy(
        update={"tool_hint": InternetTool.BROWSER_USE, "needs_interaction": True}
    )
    actor = str(getattr(request.state, "user_id", "unknown"))
    actor_type = _approval_actor_type(request)
    plan = InternetScoutOrchestrator().plan(browser_body)
    if plan.decision.tool != InternetTool.BROWSER_USE:
        raise HTTPException(status_code=400, detail="browser_use_request_required")
    if not plan.decision.requires_approval:
        raise HTTPException(status_code=400, detail="browser_use_approval_not_required")

    async with rls_connection(request) as conn:
        repo = InternetScoutRepository(conn)
        request_id = await repo.create_request(
            user_id=actor,
            request=browser_body,
            decision=plan.decision,
        )
        queue_id = await enqueue_browser_task_approval(
            conn,
            request=browser_body,
            decision=plan.decision,
            actor_sub=actor,
            actor_type=actor_type,
            nonce=uuid4().hex,
        )
        await repo.record_tool_event(
            request_id=request_id,
            tool=plan.decision.tool.value,
            event_type="approval_request",
            status="queued",
            metadata={
                "approval_queue_id": str(queue_id),
                "approval_status": "pending",
                "requires_approval": True,
            },
        )

    logger.info(
        "BEACON_BROWSER_APPROVAL_QUEUED",
        extra={
            "event": "BEACON_BROWSER_APPROVAL_QUEUED",
            "request_id": str(request_id),
            "approval_queue_id": str(queue_id),
            "risk_tier": plan.decision.tier,
            "sensitivity": browser_body.sensitivity,
        },
    )
    return InternetScoutBrowserApprovalResponse(
        request_id=request_id,
        approval_queue_id=queue_id,
        plan=plan,
    )


@router.get("/requests/{request_id}", response_model=InternetScoutStoredResponse)
async def internet_scout_request(
    request_id: UUID,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutStoredResponse:
    """Load stored Beacon evidence for the current RLS-visible caller."""
    check_scopes(request, "internet_scout.read", "admin")

    async with rls_connection(request) as conn:
        repo = InternetScoutRepository(conn)
        packet = await repo.load_packet(request_id)
    if packet is None:
        raise HTTPException(status_code=404, detail="Beacon request not found")

    plan = InternetScoutOrchestrator().plan(packet.request)
    return InternetScoutStoredResponse(
        request_id=request_id,
        plan=plan,
        evidence=packet,
    )


def _approval_actor_type(request: Request) -> str:
    actor_type = str(getattr(request.state, "actor_type", "user"))
    if actor_type not in {"user", "service", "agent"}:
        return "user"
    return actor_type
