"""Beacon internet evidence routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from brain.db.rls import rls_connection
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.services.internet_scout.executor import InternetScoutExecutor
from brain.services.internet_scout.models import (
    InternetScoutRequest,
    InternetScoutStoredResponse,
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
