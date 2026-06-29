"""Beacon internet evidence routes."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from brain.db.rls import platform_admin_connection, rls_connection
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.services.internet_scout.browser_approvals import (
    BrowserApprovalError,
    browser_task_parameters_hash,
    browser_task_approval_preview,
    consume_browser_task_approval,
    enqueue_browser_task_approval,
    require_approved_browser_task,
)
from brain.services.internet_scout.browser_runner import (
    BrowserRuntimeUnavailableError,
    BrowserSandboxPolicyError,
    browser_hourly_run_limit,
    build_browser_task_runner_from_env,
    normalize_browser_request,
)
from brain.services.internet_scout.agent import (
    build_agent_completed_response,
    build_agent_policy_response,
)
from brain.services.internet_scout.consumers import (
    BeaconConsumerPolicyError,
    build_consumer_internet_request,
)
from brain.services.internet_scout.executor import InternetScoutExecutor
from brain.services.internet_scout.local_llm import build_local_llm_response
from brain.services.internet_scout.health import build_beacon_health
from brain.services.internet_scout.memory_promotions import MemoryPromotionPolicyError
from brain.services.internet_scout.models import (
    BrowserActionAuditEvent,
    InternetScoutAgentResponse,
    InternetScoutBrowserApprovalResponse,
    InternetScoutBrowserHistoryItem,
    InternetScoutBrowserHistoryResponse,
    InternetScoutBrowserRunRequest,
    InternetScoutBrowserRunResponse,
    InternetScoutConsumerRequest,
    InternetScoutHealthResponse,
    InternetScoutLocalLLMResponse,
    InternetScoutMemoryPromotionCreateRequest,
    InternetScoutMemoryPromotionCreateResponse,
    InternetScoutMemoryPromotionReviewRequest,
    InternetScoutMemoryPromotionReviewResponse,
    InternetScoutRequest,
    InternetScoutRetentionDeleteRequest,
    InternetScoutRetentionDeleteResponse,
    InternetScoutRetentionReport,
    InternetScoutStoredResponse,
    InternetTool,
)
from brain.services.internet_scout.orchestrator import InternetScoutOrchestrator
from brain.services.internet_scout.repository import InternetScoutRepository
from brain.services.internet_scout.retention import (
    build_retention_report,
    delete_expired_evidence,
)
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")
router = APIRouter(prefix="/v1/internet-scout", tags=["internet-scout"])

BROWSER_HISTORY_EVENT_TYPES = {
    "approval_request",
    "browser_run",
    "browser_action",
}


@router.get("/health", response_model=InternetScoutHealthResponse)
async def internet_scout_health(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutHealthResponse:
    """Return Beacon production readiness without exposing provider secrets."""
    check_scopes(request, "internet_scout.read", "admin")
    async with rls_connection(request) as conn:
        return await build_beacon_health(conn)


@router.get("/retention/report", response_model=InternetScoutRetentionReport)
async def internet_scout_retention_report(
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutRetentionReport:
    """Report retention candidates only; never delete evidence."""
    check_scopes(request, "internet_scout.read", "admin")
    async with rls_connection(request) as conn:
        return await build_retention_report(conn)


@router.post(
    "/retention/delete-expired",
    response_model=InternetScoutRetentionDeleteResponse,
)
async def internet_scout_retention_delete_expired(
    body: InternetScoutRetentionDeleteRequest,
    request: Request,
    user_id: str = Depends(require_auth),
) -> InternetScoutRetentionDeleteResponse:
    """Apply reviewed Beacon retention cleanup with dry-run and env gates."""
    check_scopes(request, "admin")
    async with platform_admin_connection(
        source="http",
        audit_actor=f"beacon_retention_delete:{user_id}",
    ) as conn:
        return await delete_expired_evidence(conn, body)


@router.post("/research", response_model=InternetScoutStoredResponse)
async def internet_scout_research(
    body: InternetScoutRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutStoredResponse:
    """Run a Beacon research request and store structured evidence."""
    check_scopes(request, "internet_scout.research", "admin")
    return await _execute_and_store_research(body, request)


@router.post("/local-llm/tool", response_model=InternetScoutLocalLLMResponse)
async def internet_scout_local_llm_tool(
    body: InternetScoutRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutLocalLLMResponse:
    """Return Beacon evidence in a local-LLM-safe citation envelope."""
    check_scopes(request, "internet_scout.research", "admin")
    stored = await _execute_and_store_research(body, request)
    return build_local_llm_response(stored)


@router.post("/agent/run", response_model=InternetScoutAgentResponse)
async def internet_scout_agent_run(
    body: InternetScoutRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutAgentResponse:
    """Run Beacon through the production agent envelope."""
    check_scopes(request, "internet_scout.research", "admin")
    plan = InternetScoutOrchestrator().plan(body)
    if not plan.decision.allowed:
        request_id = await _record_policy_only_request(body, request)
        return build_agent_policy_response(plan=plan, request_id=request_id)

    stored = await _execute_and_store_research(body, request)
    response = build_agent_completed_response(stored)
    logger.info(
        "BEACON_AGENT_RUN",
        extra={
            "event": "BEACON_AGENT_RUN",
            "request_id": str(stored.request_id),
            "tool": response.selected_tool.value,
            "status": response.status,
            "citation_count": len(response.citations),
            "confidence": response.confidence,
        },
    )
    return response


@router.post(
    "/consumers/{consumer}/local-llm/tool",
    response_model=InternetScoutLocalLLMResponse,
)
async def internet_scout_consumer_local_llm_tool(
    consumer: str,
    body: InternetScoutConsumerRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutLocalLLMResponse:
    """Return policy-scoped Beacon evidence for a registered consumer."""
    check_scopes(
        request,
        "internet_scout.research",
        "internet_scout.consumer",
        f"internet_scout.consumer.{consumer}",
        "admin",
    )
    try:
        scout_request = build_consumer_internet_request(consumer, body)
    except BeaconConsumerPolicyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    stored = await _execute_and_store_research(scout_request, request)
    return build_local_llm_response(stored)


async def _execute_and_store_research(
    body: InternetScoutRequest,
    request: Request,
) -> InternetScoutStoredResponse:
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


async def _record_policy_only_request(
    body: InternetScoutRequest,
    request: Request,
) -> UUID:
    actor = str(getattr(request.state, "user_id", "unknown"))
    plan = InternetScoutOrchestrator().plan(body)
    async with rls_connection(request) as conn:
        repo = InternetScoutRepository(conn)
        request_id = await repo.create_request(
            user_id=actor,
            request=body,
            decision=plan.decision,
        )
        await repo.record_tool_event(
            request_id=request_id,
            tool=plan.decision.tool.value,
            event_type="policy",
            status="blocked",
            metadata={
                "requires_approval": plan.decision.requires_approval,
                "blocked_reasons": plan.decision.blocked_reasons,
            },
        )
    logger.info(
        "BEACON_AGENT_POLICY_ONLY",
        extra={
            "event": "BEACON_AGENT_POLICY_ONLY",
            "request_id": str(request_id),
            "tool": plan.decision.tool.value,
            "requires_approval": plan.decision.requires_approval,
            "tier": plan.decision.tier,
        },
    )
    return request_id


@router.post(
    "/requests/{request_id}/memory-promotions",
    response_model=InternetScoutMemoryPromotionCreateResponse,
)
async def internet_scout_create_memory_promotions(
    request_id: UUID,
    body: InternetScoutMemoryPromotionCreateRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutMemoryPromotionCreateResponse:
    """Create reviewed memory-promotion candidates from stored Beacon evidence."""
    check_scopes(request, "internet_scout.memory_promote", "admin")
    actor = str(getattr(request.state, "user_id", "unknown"))
    async with rls_connection(request) as conn:
        repo = InternetScoutRepository(conn)
        packet = await repo.load_packet(request_id)
        if packet is None:
            raise HTTPException(status_code=404, detail="Beacon request not found")
        try:
            promotions = await repo.create_memory_promotions(
                request_id=request_id,
                packet=packet,
                target_user_id=body.target_user_id,
                requested_by=actor,
                candidates=body.candidates,
            )
        except MemoryPromotionPolicyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return InternetScoutMemoryPromotionCreateResponse(
        request_id=request_id,
        promotions=promotions,
    )


@router.post(
    "/memory-promotions/{promotion_id}/review",
    response_model=InternetScoutMemoryPromotionReviewResponse,
)
async def internet_scout_review_memory_promotion(
    promotion_id: UUID,
    body: InternetScoutMemoryPromotionReviewRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutMemoryPromotionReviewResponse:
    """Approve or reject a Beacon memory promotion candidate."""
    check_scopes(request, "internet_scout.memory_promote", "admin")
    reviewer = str(getattr(request.state, "user_id", "unknown"))
    async with rls_connection(request) as conn:
        promotion = await InternetScoutRepository(conn).review_memory_promotion(
            promotion_id=promotion_id,
            decision=body.decision,
            reviewer=reviewer,
            reviewer_note=body.reviewer_note,
        )
    if promotion is None:
        raise HTTPException(status_code=404, detail="Beacon promotion not found")
    return InternetScoutMemoryPromotionReviewResponse(promotion=promotion)


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
    preview = browser_task_approval_preview(browser_body, plan.decision)

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
                "approval_hash_prefix": preview.approval_hash_prefix,
                "browser_action_preview": preview.model_dump(mode="json"),
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
        preview=preview,
    )


@router.post(
    "/browser-task/run-approved",
    response_model=InternetScoutBrowserRunResponse,
)
async def internet_scout_browser_run_approved(
    body: InternetScoutBrowserRunRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutBrowserRunResponse:
    """Execute an already-approved browser task through the P8 sandbox."""
    check_scopes(request, "internet_scout.research", "admin")
    browser_body = normalize_browser_request(body.browser_request)
    actor = str(getattr(request.state, "user_id", "unknown"))
    plan = InternetScoutOrchestrator().plan(browser_body)
    if plan.decision.tool != InternetTool.BROWSER_USE:
        raise HTTPException(status_code=400, detail="browser_use_request_required")
    if not plan.decision.requires_approval:
        raise HTTPException(status_code=400, detail="browser_use_approval_not_required")
    parameters_hash = browser_task_parameters_hash(browser_body, plan.decision)

    async with rls_connection(request) as conn:
        try:
            await require_approved_browser_task(
                conn,
                approval_queue_id=body.approval_queue_id,
                actor_sub=actor,
                parameters_hash=parameters_hash,
            )
        except BrowserApprovalError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

        repo = InternetScoutRepository(conn)
        max_runs = browser_hourly_run_limit()
        recent_runs = await repo.count_recent_browser_runs(actor)
        if recent_runs >= max_runs:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "browser_run_quota_exceeded",
                    "max_runs_per_hour": max_runs,
                },
            )
        request_id = await repo.create_request(
            user_id=actor,
            request=browser_body,
            decision=plan.decision,
            status_override="running",
        )
        await repo.record_tool_event(
            request_id=request_id,
            tool=plan.decision.tool.value,
            event_type="browser_run",
            status="started",
            metadata={
                "approval_queue_id": str(body.approval_queue_id),
                "max_steps": body.max_steps,
                "require_screenshot": body.require_screenshot,
            },
        )

    try:
        result = await build_browser_task_runner_from_env().execute(
            request_id=request_id,
            approval_queue_id=body.approval_queue_id,
            request=browser_body,
            plan=plan,
            max_steps=body.max_steps,
            require_screenshot=body.require_screenshot,
            audit_action=lambda event: _record_browser_action_audit_event(
                request=request,
                request_id=request_id,
                tool=plan.decision.tool,
                approval_queue_id=body.approval_queue_id,
                parameters_hash=parameters_hash,
                event=event,
            ),
        )
    except BrowserSandboxPolicyError as exc:
        await _mark_browser_run_failed(
            request, request_id, plan.decision.tool, str(exc)
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BrowserRuntimeUnavailableError as exc:
        await _mark_browser_run_failed(
            request, request_id, plan.decision.tool, str(exc)
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        await _mark_browser_run_failed(
            request, request_id, plan.decision.tool, str(exc)
        )
        raise

    async with rls_connection(request) as conn:
        repo = InternetScoutRepository(conn)
        await repo.store_packet(request_id=request_id, packet=result.evidence)
        await repo.record_tool_event(
            request_id=request_id,
            tool=plan.decision.tool.value,
            event_type="browser_run",
            status="succeeded",
            metadata={
                "approval_queue_id": str(body.approval_queue_id),
                "observation_count": len(result.observations),
                "screenshot_count": len(
                    [
                        observation
                        for observation in result.observations
                        if observation.screenshot_ref
                    ]
                ),
                "screenshots_review_required": True,
                "action_audit_count": len(result.action_audit),
            },
        )
        await repo.mark_request_succeeded(request_id)
        await consume_browser_task_approval(
            conn,
            approval_queue_id=body.approval_queue_id,
        )

    return result


@router.get(
    "/browser-task/history",
    response_model=InternetScoutBrowserHistoryResponse,
)
async def internet_scout_browser_history(
    request: Request,
    _user_id: str = Depends(require_auth),
    limit: int = 20,
    offset: int = 0,
    event_type: str | None = None,
    q: str | None = None,
) -> InternetScoutBrowserHistoryResponse:
    """Return recent Beacon browser approval/run audit events for operator review."""
    check_scopes(request, "internet_scout.read", "admin")
    safe_limit = min(max(limit, 1), 50)
    safe_offset = max(offset, 0)
    normalized_event_type = event_type or None
    if normalized_event_type and len(normalized_event_type) > 64:
        raise HTTPException(
            status_code=400, detail="Invalid browser history event type"
        )
    if (
        normalized_event_type
        and normalized_event_type not in BROWSER_HISTORY_EVENT_TYPES
    ):
        raise HTTPException(
            status_code=400, detail="Invalid browser history event type"
        )
    if q and len(q) > 120:
        raise HTTPException(
            status_code=400, detail="Browser history search is too long"
        )
    search = q.strip().lower() if q else ""
    search_pattern = f"%{search}%" if search else None
    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            """
            SELECT
                event.request_id,
                event.event_type,
                event.status,
                event.created_at,
                request.selected_tool,
                request.status AS request_status,
                request.policy_tier AS risk_tier,
                event.metadata->>'approval_queue_id' AS approval_queue_id,
                event.metadata->>'approval_hash_prefix' AS approval_hash_prefix,
                CASE
                    WHEN event.metadata->>'observation_count' ~ '^[0-9]+$'
                    THEN (event.metadata->>'observation_count')::integer
                    ELSE 0
                END AS observation_count,
                CASE
                    WHEN event.metadata->>'screenshot_count' ~ '^[0-9]+$'
                    THEN (event.metadata->>'screenshot_count')::integer
                    ELSE 0
                END AS screenshot_count,
                CASE
                    WHEN event.metadata->>'action_audit_count' ~ '^[0-9]+$'
                    THEN (event.metadata->>'action_audit_count')::integer
                    ELSE 0
                END AS action_audit_count,
                event.metadata->>'action' AS action,
                event.metadata->>'host' AS host,
                event.metadata->>'blocked_reason' AS blocked_reason,
                CASE
                    WHEN event.metadata->>'elapsed_ms' ~ '^[0-9]+$'
                    THEN (event.metadata->>'elapsed_ms')::integer
                    ELSE NULL
                END AS elapsed_ms
            FROM public.alpha_internet_tool_events AS event
            JOIN public.alpha_internet_requests AS request
              ON request.id = event.request_id
            WHERE event.tool = 'browser_use'
              AND event.event_type IN (
                  'approval_request',
                  'browser_run',
                  'browser_action'
              )
              AND ($1::text IS NULL OR event.event_type = $1)
              AND (
                  $2::text IS NULL
                  OR lower(
                      event.request_id::text || ' ' ||
                      event.event_type || ' ' ||
                      event.status || ' ' ||
                      request.status || ' ' ||
                      COALESCE(request.policy_tier::text, '') || ' ' ||
                      COALESCE(event.metadata->>'approval_queue_id', '') || ' ' ||
                      COALESCE(event.metadata->>'approval_hash_prefix', '') || ' ' ||
                      COALESCE(event.metadata->>'action', '') || ' ' ||
                      COALESCE(event.metadata->>'host', '') || ' ' ||
                      COALESCE(event.metadata->>'blocked_reason', '')
                  ) LIKE $2
              )
            ORDER BY event.created_at DESC, event.id DESC
            LIMIT $3
            OFFSET $4
            """,
            normalized_event_type,
            search_pattern,
            safe_limit + 1,
            safe_offset,
        )
    page_rows = rows[:safe_limit]
    history = [
        InternetScoutBrowserHistoryItem(
            request_id=row["request_id"],
            approval_queue_id=_optional_uuid(row["approval_queue_id"]),
            event_type=row["event_type"],
            status=row["status"],
            created_at=row["created_at"],
            selected_tool=row["selected_tool"],
            request_status=row["request_status"],
            risk_tier=row["risk_tier"],
            approval_hash_prefix=row["approval_hash_prefix"],
            observation_count=int(row["observation_count"] or 0),
            screenshot_count=int(row["screenshot_count"] or 0),
            action_audit_count=int(row["action_audit_count"] or 0),
            action=row["action"],
            host=row["host"],
            blocked_reason=row["blocked_reason"],
            elapsed_ms=(
                int(row["elapsed_ms"]) if row["elapsed_ms"] is not None else None
            ),
        )
        for row in page_rows
    ]
    return InternetScoutBrowserHistoryResponse(
        history=history,
        count=len(history),
        limit=safe_limit,
        offset=safe_offset,
        has_more=len(rows) > safe_limit,
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


async def _mark_browser_run_failed(
    request: Request,
    request_id: UUID,
    tool: InternetTool,
    error_text: str,
) -> None:
    async with rls_connection(request) as conn:
        repo = InternetScoutRepository(conn)
        await repo.record_tool_event(
            request_id=request_id,
            tool=tool.value,
            event_type="browser_run",
            status="failed",
            error_text=error_text,
        )
        await repo.mark_request_failed(request_id, error_text)


async def _record_browser_action_audit_event(
    *,
    request: Request,
    request_id: UUID,
    tool: InternetTool,
    approval_queue_id: UUID,
    parameters_hash: str,
    event: BrowserActionAuditEvent,
) -> None:
    metadata = event.model_dump(mode="json", exclude_none=True)
    metadata.update(
        {
            "approval_queue_id": str(approval_queue_id),
            "approval_hash_prefix": parameters_hash[:12],
            "raw_task_text_included": False,
            "raw_web_content_included": False,
            "downloads_allowed": False,
            "forms_allowed": False,
            "credential_entry_allowed": False,
        }
    )
    async with rls_connection(request) as conn:
        repo = InternetScoutRepository(conn)
        await repo.record_tool_event(
            request_id=request_id,
            tool=tool.value,
            event_type="browser_action",
            status=event.status,
            metadata=metadata,
        )


def _approval_actor_type(request: Request) -> str:
    actor_type = str(getattr(request.state, "actor_type", "user"))
    if actor_type not in {"user", "service", "agent"}:
        return "user"
    return actor_type


def _optional_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None
