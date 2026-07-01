"""Beacon internet evidence routes."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

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
from brain.services.internet_scout.crawler import InternetScoutCrawler
from brain.services.internet_scout.executor import InternetScoutExecutor
from brain.services.internet_scout.local_llm import build_local_llm_response
from brain.services.internet_scout.health import build_beacon_health
from brain.services.internet_scout.memory_promotions import MemoryPromotionPolicyError
from brain.services.internet_scout.models import (
    BrowserActionAuditEvent,
    BrowserRunObservation,
    InternetScoutAgentResponse,
    InternetScoutBrowserApprovalResponse,
    InternetScoutBrowserHistoryItem,
    InternetScoutBrowserHistoryResponse,
    InternetScoutBrowserRunRequest,
    InternetScoutBrowserRunResponse,
    InternetScoutConsumerRequest,
    InternetScoutCrawlerBatchScrapeItem,
    InternetScoutCrawlerBatchScrapeRequest,
    InternetScoutCrawlerBatchScrapeResponse,
    InternetScoutCrawlerCrawlRequest,
    InternetScoutCrawlerExtractRequest,
    InternetScoutCrawlerExtractResponse,
    InternetScoutCrawlerMapRequest,
    InternetScoutCrawlerMapResponse,
    InternetScoutCrawlerRenderResponse,
    InternetScoutCrawlerRenderRunRequest,
    InternetScoutCrawlerScrapeRequest,
    InternetScoutCrawlerScrapeResponse,
    InternetScoutHealthResponse,
    InternetScoutLocalLLMResponse,
    InternetScoutMemoryPromotionCreateRequest,
    InternetScoutMemoryPromotionCreateResponse,
    InternetScoutMemoryPromotionReviewRequest,
    InternetScoutMemoryPromotionReviewResponse,
    InternetScoutRequest,
    InternetScoutRequestHistoryItem,
    InternetScoutRequestHistoryResponse,
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
REQUEST_HISTORY_STATUSES = {"running", "succeeded", "failed", "blocked"}
CRAWLER_EVENTS = {
    "scrape": "crawler_scrape",
    "map": "crawler_map",
    "crawl": "crawler_crawl",
    "extract": "crawler_extract",
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


@router.post("/local-llm/tool/stream")
async def internet_scout_local_llm_tool_stream(
    body: InternetScoutRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> StreamingResponse:
    """Stream Beacon research lifecycle events before the final citation envelope."""
    check_scopes(request, "internet_scout.research", "admin")
    return StreamingResponse(
        _stream_local_llm_tool(body, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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


async def _stream_local_llm_tool(
    body: InternetScoutRequest,
    request: Request,
) -> AsyncIterator[str]:
    plan = InternetScoutOrchestrator().plan(body)
    yield _sse_event(
        "step",
        {
            "stage": "planned",
            "status": "completed",
            "detail": "Research plan prepared.",
            "plan_id": plan.research.plan_id,
            "intent": plan.research.intent,
            "max_searches": plan.research.max_searches,
            "max_extracts": plan.research.max_extracts,
            "min_accepted_citations": (
                plan.research.stop_criteria.min_accepted_citations
            ),
            "expected_source_types": plan.research.expected_source_types,
        },
    )
    yield _sse_event(
        "step",
        {
            "stage": "executing",
            "status": "started",
            "detail": "Provider route and extract path running.",
            "provider_strategy": plan.research.provider_strategy,
            "search_providers": plan.research.search_providers,
        },
    )
    try:
        stored = await _execute_and_store_research(body, request)
        yield _sse_event(
            "step",
            {
                "stage": "synthesizing",
                "status": "started",
                "detail": "Ranking citations and building evidence bundle.",
                "source_count": len(stored.evidence.sources),
                "claim_count": len(stored.evidence.claims),
            },
        )
        response = build_local_llm_response(stored)
        yield _sse_event(
            "completed",
            response.model_dump(mode="json"),
        )
    except Exception as exc:
        logger.warning(
            "BEACON_LOCAL_LLM_STREAM_FAIL",
            extra={
                "event": "BEACON_LOCAL_LLM_STREAM_FAIL",
                "stage": "failed",
                "error_type": type(exc).__name__,
            },
        )
        failure_detail = _stream_failure_detail(exc)
        yield _sse_event(
            "failed",
            {
                "stage": "failed",
                "status": "failed",
                "detail": failure_detail["detail"],
                "error_type": type(exc).__name__,
                "request_id": failure_detail.get("request_id"),
            },
        )


def _sse_event(event: str, payload: dict[str, object]) -> str:
    data = json.dumps(payload, default=str, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"


def _stream_failure_detail(exc: Exception) -> dict[str, str | None]:
    if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
        request_id = exc.detail.get("request_id")
        error = str(exc.detail.get("error") or "beacon_stream_failed")
        return {
            "detail": error,
            "request_id": str(request_id) if request_id else None,
        }
    if isinstance(exc, HTTPException):
        return {"detail": str(exc.detail)[:240], "request_id": None}
    return {
        "detail": "Beacon request failed before completion.",
        "request_id": None,
    }


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


@router.post("/crawler/scrape", response_model=InternetScoutCrawlerScrapeResponse)
async def internet_scout_crawler_scrape(
    body: InternetScoutCrawlerScrapeRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutCrawlerScrapeResponse:
    """Scrape one public URL through Beacon cache and Gateway egress."""
    check_scopes(request, "internet_scout.research", "admin")
    return await _execute_crawler(
        operation="scrape",
        body=body,
        scout_request=InternetScoutRequest(
            query=body.query,
            urls=[body.url],
            tool_hint=InternetTool.EXTRACT,
            requester="alpha_ui.beacon_crawler.scrape",
        ),
        request=request,
    )


@router.post(
    "/crawler/batch-scrape",
    response_model=InternetScoutCrawlerBatchScrapeResponse,
)
async def internet_scout_crawler_batch_scrape(
    body: InternetScoutCrawlerBatchScrapeRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutCrawlerBatchScrapeResponse:
    """Scrape a small URL batch through the same audited, cache-first path."""
    check_scopes(request, "internet_scout.research", "admin")
    batch_id = uuid4()
    items: list[InternetScoutCrawlerBatchScrapeItem] = []
    for index, url in enumerate(body.urls):
        scrape_body = InternetScoutCrawlerScrapeRequest(
            url=url,
            query=body.query,
            force_refresh=body.force_refresh,
            max_bytes=body.max_bytes,
        )
        batch_metadata = {
            "batch_id": str(batch_id),
            "batch_index": index,
            "batch_size": len(body.urls),
        }
        try:
            response = await _execute_crawler(
                operation="scrape",
                body=scrape_body,
                scout_request=InternetScoutRequest(
                    query=body.query,
                    urls=[url],
                    tool_hint=InternetTool.EXTRACT,
                    requester="alpha_ui.beacon_crawler.batch_scrape",
                ),
                request=request,
                metadata_extra=batch_metadata,
            )
            items.append(_batch_scrape_success_item(url=url, response=response))
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
            items.append(_batch_scrape_blocked_item(url=url, exc=exc))
        except Exception as exc:
            items.append(
                InternetScoutCrawlerBatchScrapeItem(
                    url=url,
                    status="failed",
                    error_type=exc.__class__.__name__,
                )
            )

    return InternetScoutCrawlerBatchScrapeResponse(
        batch_id=batch_id,
        result_count=len(items),
        succeeded_count=sum(1 for item in items if item.status == "succeeded"),
        failed_count=sum(1 for item in items if item.status == "failed"),
        blocked_count=sum(1 for item in items if item.status == "blocked"),
        items=items,
    )


def _batch_scrape_success_item(
    *,
    url: str,
    response: InternetScoutCrawlerScrapeResponse,
) -> InternetScoutCrawlerBatchScrapeItem:
    return InternetScoutCrawlerBatchScrapeItem(
        url=url,
        status="succeeded",
        request_id=response.request_id,
        cache_hit=response.cache_hit,
        canonical_url=response.canonical_url,
        host=response.host,
        title=response.title,
        fetched_at=response.fetched_at,
        text=response.text,
        links=response.links,
        content_hash=response.content_hash,
        risk_markers=response.risk_markers,
    )


def _batch_scrape_blocked_item(
    *,
    url: str,
    exc: HTTPException,
) -> InternetScoutCrawlerBatchScrapeItem:
    detail = exc.detail if isinstance(exc.detail, Mapping) else {}
    decision = detail.get("decision") if isinstance(detail, Mapping) else {}
    reasons = decision.get("blocked_reasons") if isinstance(decision, Mapping) else []
    return InternetScoutCrawlerBatchScrapeItem(
        url=url,
        status="blocked",
        request_id=_uuid_or_none(detail.get("request_id")),
        blocked_reasons=[
            str(reason)[:120]
            for reason in reasons
            if isinstance(reason, str) and reason.strip()
        ][:10],
        error_type="policy_denied",
    )


def _uuid_or_none(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


@router.post(
    "/crawler/scrape/browser-approval-request",
    response_model=InternetScoutBrowserApprovalResponse,
)
async def internet_scout_crawler_scrape_browser_approval_request(
    body: InternetScoutCrawlerScrapeRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutBrowserApprovalResponse:
    """Queue a browser-rendered crawler scrape; execution stays approval-gated."""
    check_scopes(request, "internet_scout.research", "admin")
    _ensure_crawler_url_allowed(body)
    return await _queue_browser_task_approval(
        browser_body=_crawler_render_browser_request(body),
        request=request,
        extra_metadata={
            "source": "crawler_render_scrape",
            "require_screenshot": True,
            "crawler_operation": "scrape",
            "render_quality_version": 2,
            "render_quality_checks": [
                "visible_text",
                "screenshot",
                "evidence_source",
                "action_audit",
            ],
        },
    )


@router.post(
    "/crawler/scrape/browser-run-approved",
    response_model=InternetScoutCrawlerRenderResponse,
)
async def internet_scout_crawler_scrape_browser_run_approved(
    body: InternetScoutCrawlerRenderRunRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutCrawlerRenderResponse:
    """Run an approved browser-rendered scrape and return crawler-shaped output."""
    check_scopes(request, "internet_scout.research", "admin")
    _ensure_crawler_url_allowed(body.scrape)
    result = await _run_approved_browser_task(
        InternetScoutBrowserRunRequest(
            approval_queue_id=body.approval_queue_id,
            browser_request=_crawler_render_browser_request(body.scrape),
            max_steps=body.max_steps,
            require_screenshot=True,
        ),
        request,
    )
    observation = result.observations[0]
    quality_status, quality_reasons, visible_text_length = _crawler_render_quality(
        observation=observation,
        result=result,
    )
    return InternetScoutCrawlerRenderResponse(
        request_id=result.request_id,
        approval_queue_id=result.approval_queue_id,
        cache_hit=False,
        canonical_url=observation.url,
        host=observation.host,
        title=observation.title,
        fetched_at=observation.fetched_at,
        text=observation.visible_text,
        links=[],
        screenshot_ref=observation.screenshot_ref,
        content_hash=observation.content_hash,
        risk_markers=observation.risk_markers,
        evidence_path=f"/v1/internet-scout/requests/{result.request_id}",
        audit_path=(
            f"/v1/internet-scout/browser-task/history?q={result.approval_queue_id}"
        ),
        action_audit_count=len(result.action_audit),
        evidence_source_count=len(result.evidence.sources),
        render_quality_status=quality_status,
        render_quality_reasons=quality_reasons,
        visible_text_length=visible_text_length,
    )


def _crawler_render_quality(
    *,
    observation: BrowserRunObservation,
    result: InternetScoutBrowserRunResponse,
) -> tuple[str, list[str], int]:
    metadata = _browser_render_quality_metadata(
        observations=[observation],
        evidence_source_count=len(result.evidence.sources),
        action_audit_count=len(result.action_audit),
        require_screenshot=True,
    )
    return (
        str(metadata["render_quality_status"]),
        list(metadata["render_quality_reasons"]),
        int(metadata["visible_text_length"]),
    )


def _browser_render_quality_metadata(
    *,
    observations: list[BrowserRunObservation],
    evidence_source_count: int,
    action_audit_count: int,
    require_screenshot: bool,
) -> dict[str, object]:
    observation = observations[0] if observations else None
    visible_text = observation.visible_text.strip() if observation else ""
    visible_text_length = len(visible_text)
    screenshot_count = len(
        [item for item in observations if item.screenshot_ref],
    )
    reasons: list[str] = []
    if not observation:
        reasons.append("missing_observation")
    if not visible_text:
        reasons.append("empty_visible_text")
    elif visible_text_length < 80:
        reasons.append("short_visible_text")
    if require_screenshot and screenshot_count == 0:
        reasons.append("missing_screenshot")
    if evidence_source_count <= 0:
        reasons.append("missing_evidence_source")
    if action_audit_count <= 0:
        reasons.append("missing_action_audit")
    status = "empty" if "empty_visible_text" in reasons else "weak" if reasons else "ok"
    return {
        "render_quality_version": 2,
        "render_quality_status": status,
        "render_quality_reasons": reasons[:10],
        "visible_text_length": visible_text_length,
        "missing_screenshot": "missing_screenshot" in reasons,
        "missing_evidence": "missing_evidence_source" in reasons,
    }


def _browser_run_source(requester: str | None) -> str:
    if requester == "alpha_ui.beacon_crawler.render_scrape":
        return "crawler_render_scrape"
    return "browser_task"


def _crawler_render_browser_request(
    body: InternetScoutCrawlerScrapeRequest,
) -> InternetScoutRequest:
    return InternetScoutRequest(
        query=body.query,
        urls=[body.url],
        tool_hint=InternetTool.BROWSER_USE,
        max_pages=1,
        max_depth=0,
        needs_interaction=True,
        requester="alpha_ui.beacon_crawler.render_scrape",
    )


def _ensure_crawler_url_allowed(body: InternetScoutCrawlerScrapeRequest) -> None:
    safety_plan = InternetScoutOrchestrator().plan(
        InternetScoutRequest(
            urls=[body.url],
            tool_hint=InternetTool.EXTRACT,
            requester="alpha_ui.beacon_crawler.render_safety",
        )
    )
    if not safety_plan.decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "beacon_crawler_policy_denied",
                "decision": safety_plan.decision.model_dump(mode="json"),
            },
        )


@router.post("/crawler/map", response_model=InternetScoutCrawlerMapResponse)
async def internet_scout_crawler_map(
    body: InternetScoutCrawlerMapRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutCrawlerMapResponse:
    """Map same-host links with bounded public crawl caps."""
    check_scopes(request, "internet_scout.research", "admin")
    return await _execute_crawler(
        operation="map",
        body=body,
        scout_request=InternetScoutRequest(
            urls=[body.url],
            tool_hint=InternetTool.CRAWL,
            max_pages=body.max_pages,
            max_depth=body.max_depth,
            requester="alpha_ui.beacon_crawler.map",
        ),
        request=request,
    )


@router.post("/crawler/crawl", response_model=InternetScoutCrawlerMapResponse)
async def internet_scout_crawler_crawl(
    body: InternetScoutCrawlerCrawlRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutCrawlerMapResponse:
    """Crawl same-host public pages with strict page/depth caps."""
    check_scopes(request, "internet_scout.research", "admin")
    return await _execute_crawler(
        operation="crawl",
        body=body,
        scout_request=InternetScoutRequest(
            urls=[body.url],
            tool_hint=InternetTool.CRAWL,
            max_pages=body.max_pages,
            max_depth=body.max_depth,
            requester="alpha_ui.beacon_crawler.crawl",
        ),
        request=request,
    )


@router.post("/crawler/extract", response_model=InternetScoutCrawlerExtractResponse)
async def internet_scout_crawler_extract(
    body: InternetScoutCrawlerExtractRequest,
    request: Request,
    _user_id: str = Depends(require_auth),
) -> InternetScoutCrawlerExtractResponse:
    """Extract simple schema fields with evidence snippets from scraped text."""
    check_scopes(request, "internet_scout.research", "admin")
    return await _execute_crawler(
        operation="extract",
        body=body,
        scout_request=InternetScoutRequest(
            query=body.query,
            urls=[body.url],
            tool_hint=InternetTool.EXTRACT,
            requester="alpha_ui.beacon_crawler.extract",
        ),
        request=request,
    )


async def _execute_crawler(
    *,
    operation: str,
    body: (
        InternetScoutCrawlerScrapeRequest
        | InternetScoutCrawlerMapRequest
        | InternetScoutCrawlerCrawlRequest
        | InternetScoutCrawlerExtractRequest
    ),
    scout_request: InternetScoutRequest,
    request: Request,
    metadata_extra: dict[str, object] | None = None,
):
    actor = str(getattr(request.state, "user_id", "unknown"))
    plan = InternetScoutOrchestrator().plan(scout_request)
    event_type = CRAWLER_EVENTS[operation]
    extra_metadata = metadata_extra or {}

    async with rls_connection(request) as conn:
        repo = InternetScoutRepository(conn)
        request_id = await repo.create_request(
            user_id=actor,
            request=scout_request,
            decision=plan.decision,
        )
        if not plan.decision.allowed:
            await repo.record_tool_event(
                request_id=request_id,
                tool=plan.decision.tool.value,
                event_type=event_type,
                status="blocked",
                metadata={
                    "operation": operation,
                    "blocked_reasons": plan.decision.blocked_reasons,
                    "same_host_required": True,
                    "forms_allowed": False,
                    "credential_entry_allowed": False,
                    **extra_metadata,
                },
            )

    if not plan.decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "beacon_crawler_policy_denied",
                "request_id": str(request_id),
                "decision": plan.decision.model_dump(mode="json"),
            },
        )

    try:
        async with rls_connection(request) as conn:
            await InternetScoutRepository(conn).record_tool_event(
                request_id=request_id,
                tool=plan.decision.tool.value,
                event_type=event_type,
                status="started",
                metadata={"operation": operation, **extra_metadata},
            )

        async def cache_lookup(url: str, query: str | None):
            async with rls_connection(request) as cache_conn:
                return await InternetScoutRepository(
                    cache_conn
                ).web_cache_extract_response(url=url, query=query)

        crawler = InternetScoutCrawler()
        if operation == "scrape":
            response, packet, metadata = await crawler.scrape(
                body,
                request_id,
                scout_request,
                cache_lookup=cache_lookup,
            )
        elif operation == "map":
            response, packet, metadata = await crawler.map(
                body,
                request_id,
                scout_request,
            )
        elif operation == "crawl":
            response, packet, metadata = await crawler.crawl(
                body,
                request_id,
                scout_request,
            )
        else:
            response, packet, metadata = await crawler.extract(
                body,
                request_id,
                scout_request,
                cache_lookup=cache_lookup,
            )
        metadata.update(extra_metadata)

        async with rls_connection(request) as conn:
            repo = InternetScoutRepository(conn)
            await repo.store_packet(request_id=request_id, packet=packet)
            await repo.record_tool_event(
                request_id=request_id,
                tool=plan.decision.tool.value,
                event_type=event_type,
                status="succeeded",
                metadata=metadata,
            )
            await repo.mark_request_succeeded(request_id)
        return response
    except Exception as exc:
        safe_error_text = "Beacon crawler request failed."
        async with rls_connection(request) as conn:
            repo = InternetScoutRepository(conn)
            await repo.record_tool_event(
                request_id=request_id,
                tool=plan.decision.tool.value,
                event_type=event_type,
                status="failed",
                metadata={
                    "operation": operation,
                    "error_type": exc.__class__.__name__,
                    **extra_metadata,
                },
                error_text=safe_error_text,
            )
            await repo.mark_request_failed(request_id, safe_error_text)
        raise


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

        async def web_cache_extract(url: str, query: str | None):
            async with rls_connection(request) as cache_conn:
                return await InternetScoutRepository(
                    cache_conn
                ).web_cache_extract_response(url=url, query=query)

        executor = InternetScoutExecutor()
        executor.web_cache_extract = web_cache_extract
        _decision, packet = await executor.execute(body, plan=plan)

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
    return await _queue_browser_task_approval(
        browser_body=browser_body,
        request=request,
    )


async def _queue_browser_task_approval(
    *,
    browser_body: InternetScoutRequest,
    request: Request,
    extra_metadata: dict[str, object] | None = None,
) -> InternetScoutBrowserApprovalResponse:
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
                **(extra_metadata or {}),
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
    return await _run_approved_browser_task(body, request)


async def _run_approved_browser_task(
    body: InternetScoutBrowserRunRequest,
    request: Request,
) -> InternetScoutBrowserRunResponse:
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
        screenshot_count = len(
            [
                observation
                for observation in result.observations
                if observation.screenshot_ref
            ]
        )
        render_quality = _browser_render_quality_metadata(
            observations=result.observations,
            evidence_source_count=len(result.evidence.sources),
            action_audit_count=len(result.action_audit),
            require_screenshot=body.require_screenshot,
        )
        await repo.record_tool_event(
            request_id=request_id,
            tool=plan.decision.tool.value,
            event_type="browser_run",
            status="succeeded",
            metadata={
                "approval_queue_id": str(body.approval_queue_id),
                "source": _browser_run_source(browser_body.requester),
                "observation_count": len(result.observations),
                "screenshot_count": screenshot_count,
                "screenshots_review_required": True,
                "action_audit_count": len(result.action_audit),
                **render_quality,
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


@router.get("/requests", response_model=InternetScoutRequestHistoryResponse)
async def internet_scout_request_history(
    request: Request,
    _user_id: str = Depends(require_auth),
    limit: int = 12,
    offset: int = 0,
    status: str | None = None,
    q: str | None = None,
) -> InternetScoutRequestHistoryResponse:
    """Return searchable saved Beacon request history without raw query text."""
    check_scopes(request, "internet_scout.read", "admin")
    safe_limit = min(max(limit, 1), 50)
    safe_offset = max(offset, 0)
    normalized_status = status or None
    if normalized_status and normalized_status not in REQUEST_HISTORY_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid Beacon history status")
    if q and len(q) > 120:
        raise HTTPException(status_code=400, detail="Beacon history search is too long")
    search = q.strip().lower() if q else ""
    search_pattern = f"%{search}%" if search else None

    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            """
            SELECT
                request.id AS request_id,
                request.requester,
                request.selected_tool,
                request.sensitivity,
                request.status,
                request.policy_tier AS risk_tier,
                request.created_at,
                request.updated_at,
                COALESCE((request.request_shape->>'has_query')::boolean, false)
                    AS has_query,
                COALESCE((request.request_shape->>'url_count')::integer, 0)
                    AS url_count,
                COALESCE((request.request_shape->>'max_pages')::integer, 1)
                    AS max_pages,
                COALESCE((request.request_shape->>'max_depth')::integer, 0)
                    AS max_depth,
                COALESCE(
                    (request.request_shape->>'needs_interaction')::boolean,
                    false
                ) AS needs_interaction,
                COALESCE(source_summary.source_count, 0) AS source_count,
                COALESCE(claim_summary.claim_count, 0) AS claim_count,
                COALESCE(event_summary.event_count, 0) AS event_count,
                COALESCE(source_summary.source_hosts, ARRAY[]::text[])
                    AS source_hosts,
                latest_event.event_type AS latest_event_type,
                latest_event.status AS latest_event_status,
                latest_event.metadata AS latest_event_metadata
            FROM public.alpha_internet_requests AS request
            LEFT JOIN LATERAL (
                SELECT COUNT(*)::integer AS source_count,
                       ARRAY(
                           SELECT DISTINCT source.host
                           FROM public.alpha_internet_sources AS source
                           WHERE source.request_id = request.id
                           ORDER BY source.host
                           LIMIT 20
                       ) AS source_hosts
                FROM public.alpha_internet_sources AS source
                WHERE source.request_id = request.id
            ) AS source_summary ON true
            LEFT JOIN LATERAL (
                SELECT COUNT(*)::integer AS claim_count
                FROM public.alpha_internet_evidence AS evidence
                WHERE evidence.request_id = request.id
            ) AS claim_summary ON true
            LEFT JOIN LATERAL (
                SELECT COUNT(*)::integer AS event_count
                FROM public.alpha_internet_tool_events AS event
                WHERE event.request_id = request.id
            ) AS event_summary ON true
            LEFT JOIN LATERAL (
                SELECT event.event_type, event.status, event.metadata
                FROM public.alpha_internet_tool_events AS event
                WHERE event.request_id = request.id
                ORDER BY event.created_at DESC, event.id DESC
                LIMIT 1
            ) AS latest_event ON true
            WHERE ($1::text IS NULL OR request.status = $1)
              AND (
                  $2::text IS NULL
                  OR lower(
                      request.id::text || ' ' ||
                      request.requester || ' ' ||
                      request.selected_tool || ' ' ||
                      request.sensitivity || ' ' ||
                      request.status || ' ' ||
                      request.policy_tier || ' ' ||
                      request.policy_reason || ' ' ||
                      COALESCE(latest_event.event_type, '') || ' ' ||
                      COALESCE(latest_event.status, '')
                  ) LIKE $2
                  OR EXISTS (
                      SELECT 1
                      FROM public.alpha_internet_sources AS source
                      WHERE source.request_id = request.id
                        AND lower(
                            source.host || ' ' || COALESCE(source.title, '')
                        ) LIKE $2
                  )
                  OR EXISTS (
                      SELECT 1
                      FROM public.alpha_internet_evidence AS evidence
                      WHERE evidence.request_id = request.id
                        AND lower(
                            evidence.claim || ' ' || evidence.confidence
                        ) LIKE $2
                  )
                  OR EXISTS (
                      SELECT 1
                      FROM public.alpha_internet_tool_events AS event
                      WHERE event.request_id = request.id
                        AND lower(
                            event.event_type || ' ' ||
                            event.status || ' ' ||
                            event.metadata::text
                        ) LIKE $2
                  )
              )
            ORDER BY request.created_at DESC, request.id DESC
            LIMIT $3
            OFFSET $4
            """,
            normalized_status,
            search_pattern,
            safe_limit + 1,
            safe_offset,
        )

    page_rows = rows[:safe_limit]
    history: list[InternetScoutRequestHistoryItem] = []
    for row in page_rows:
        metadata = _event_metadata(row["latest_event_metadata"])
        history.append(
            InternetScoutRequestHistoryItem(
                request_id=row["request_id"],
                requester=row["requester"],
                selected_tool=row["selected_tool"],
                sensitivity=row["sensitivity"],
                status=row["status"],
                risk_tier=row["risk_tier"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                has_query=bool(row["has_query"]),
                url_count=int(row["url_count"] or 0),
                max_pages=int(row["max_pages"] or 1),
                max_depth=int(row["max_depth"] or 0),
                needs_interaction=bool(row["needs_interaction"]),
                source_count=int(row["source_count"] or 0),
                claim_count=int(row["claim_count"] or 0),
                event_count=int(row["event_count"] or 0),
                source_hosts=list(row["source_hosts"] or []),
                latest_event_type=row["latest_event_type"],
                latest_event_status=row["latest_event_status"],
                crawler_operation=_event_metadata_str(
                    metadata, "operation", max_len=32
                ),
                crawler_cache_hit=_event_metadata_bool(metadata, "cache_hit"),
                crawler_page_count=_event_metadata_int(metadata, "page_count"),
                crawler_link_count=_event_metadata_int(metadata, "link_count"),
                crawler_blocked_reasons=_event_metadata_list(
                    metadata, "blocked_reasons", limit=10, max_len=80
                ),
                crawler_error_type=_event_metadata_str(
                    metadata, "error_type", max_len=80
                ),
            )
        )
    return InternetScoutRequestHistoryResponse(
        history=history,
        count=len(history),
        limit=safe_limit,
        offset=safe_offset,
        has_more=len(rows) > safe_limit,
    )


def _event_metadata(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _event_metadata_bool(
    metadata: dict[str, object],
    key: str,
) -> bool | None:
    value = metadata.get(key)
    return value if isinstance(value, bool) else None


def _event_metadata_int(
    metadata: dict[str, object],
    key: str,
) -> int:
    value = metadata.get(key)
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    return 0


def _event_metadata_str(
    metadata: dict[str, object],
    key: str,
    *,
    max_len: int,
) -> str | None:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:max_len]


def _event_metadata_list(
    metadata: dict[str, object],
    key: str,
    *,
    limit: int,
    max_len: int,
) -> list[str]:
    value = metadata.get(key)
    if not isinstance(value, list):
        return []
    return [
        item.strip()[:max_len]
        for item in value[:limit]
        if isinstance(item, str) and item.strip()
    ]


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
