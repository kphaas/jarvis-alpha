"""Beacon execution service for reviewed search/fetch egress."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import HTTPException
from jarvis_common.logging_config import get_logger

from brain.services.internet_scout.evidence import (
    packet_from_crawl_response,
    packet_from_extract_response,
    packet_from_fetch_response,
    packet_from_search_and_extract_responses,
    packet_from_search_response,
    packet_from_search_responses,
)
from brain.services.internet_scout.free_source_router import (
    FreeSourceRouteResult,
    FreeSourceRouter,
)
from brain.services.internet_scout.gateway_client import (
    InternetScoutGatewayClient,
    InternetScoutGatewayError,
)
from brain.services.internet_scout.models import (
    GatewayExtractResponse,
    GatewaySearchResponse,
    InternetEvidencePacket,
    InternetScoutPlan,
    InternetScoutResearchPlan,
    InternetScoutResearchQuery,
    InternetScoutRequest,
    InternetTool,
    PolicyDecision,
    ResearchQueryPurpose,
)
from brain.services.internet_scout.policy import (
    CRAWL_MAX_DEPTH_WITHOUT_APPROVAL,
    CRAWL_MAX_PAGES_WITHOUT_APPROVAL,
    evaluate_policy,
)
from brain.services.internet_scout.safety import DEFAULT_MAX_CONTENT_BYTES
from brain.services.internet_scout.research_planner import plan_research
from brain.services.internet_scout.search_pipeline import SearchRun, rank_search_results
from brain.services.internet_scout.source_selection import (
    BEACON_EXECUTABLE_SOURCE_DATA_SOURCE_IDS,
    assert_no_on_hold_data_sources,
)

logger = get_logger("alpha_brain")
WebCacheExtractLookup = Callable[
    [str, str | None], Awaitable[GatewayExtractResponse | None]
]


class InternetScoutExecutor:
    """Execute approved Beacon read tools through Gateway-owned egress."""

    def __init__(
        self,
        gateway_client: InternetScoutGatewayClient | None = None,
        free_source_router: FreeSourceRouter | None = None,
        web_cache_extract: WebCacheExtractLookup | None = None,
    ) -> None:
        self.gateway_client = gateway_client or InternetScoutGatewayClient()
        self.free_source_router = free_source_router or FreeSourceRouter()
        self.web_cache_extract = web_cache_extract

    async def execute(
        self,
        request: InternetScoutRequest,
        *,
        plan: InternetScoutPlan | None = None,
    ) -> tuple[PolicyDecision, InternetEvidencePacket]:
        decision = evaluate_policy(request)
        if not decision.allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "beacon_policy_denied",
                    "decision": decision.model_dump(mode="json"),
                },
            )

        if decision.tool == InternetTool.SEARCH:
            if request.query is None:
                raise HTTPException(status_code=400, detail="query is required")
            free_source_result = await self._try_free_source_route(request)
            if free_source_result is not None:
                return decision, free_source_result.packet
            research = (
                plan.research
                if plan is not None
                else plan_research(request, selected_tool=decision.tool)
            )
            search_runs = await self._run_searches(request=request, research=research)
            search_responses = [run.response for run in search_runs]
            extract_responses = await self._extract_ranked_search_results(
                request=request,
                research=research,
                search_runs=search_runs,
            )
            if extract_responses:
                return decision, packet_from_search_and_extract_responses(
                    request=request,
                    search_responses=search_responses,
                    extract_responses=extract_responses,
                )
            if len(search_responses) == 1:
                return decision, packet_from_search_response(
                    request=request,
                    response=search_responses[0],
                )
            return decision, packet_from_search_responses(
                request=request,
                responses=search_responses,
            )

        if decision.tool == InternetTool.FETCH:
            if not request.urls:
                raise HTTPException(status_code=400, detail="url is required")
            fetch_response = await self.gateway_client.fetch(
                url=request.urls[0],
                max_bytes=DEFAULT_MAX_CONTENT_BYTES,
            )
            return decision, packet_from_fetch_response(
                request=request,
                response=fetch_response,
            )

        if decision.tool == InternetTool.EXTRACT:
            if not request.urls:
                raise HTTPException(status_code=400, detail="url is required")
            cached_extract = await self._cached_extract_response(
                url=request.urls[0],
                query=request.query,
            )
            if cached_extract is not None:
                return decision, packet_from_extract_response(
                    request=request,
                    response=cached_extract,
                )
            extract_response = await self.gateway_client.extract(
                url=request.urls[0],
                max_bytes=DEFAULT_MAX_CONTENT_BYTES,
            )
            return decision, packet_from_extract_response(
                request=request,
                response=extract_response,
            )

        if decision.tool == InternetTool.CRAWL:
            if not request.urls:
                raise HTTPException(status_code=400, detail="url is required")
            crawl_response = await self.gateway_client.crawl(
                url=request.urls[0],
                max_pages=min(request.max_pages, CRAWL_MAX_PAGES_WITHOUT_APPROVAL),
                max_depth=min(request.max_depth, CRAWL_MAX_DEPTH_WITHOUT_APPROVAL),
                max_bytes=DEFAULT_MAX_CONTENT_BYTES,
            )
            return decision, packet_from_crawl_response(
                request=request,
                response=crawl_response,
            )

        raise HTTPException(
            status_code=403,
            detail=f"Beacon tool {decision.tool.value!r} is not enabled for execution",
        )

    async def _try_free_source_route(
        self, request: InternetScoutRequest
    ) -> FreeSourceRouteResult | None:
        try:
            return await self.free_source_router.try_route(request)
        except Exception as exc:
            logger.warning(
                "BEACON_FREE_SOURCE_FALLBACK",
                extra={
                    "event": "BEACON_FREE_SOURCE_FALLBACK",
                    "error_type": type(exc).__name__,
                },
            )
            return None

    async def _run_searches(
        self,
        *,
        request: InternetScoutRequest,
        research: InternetScoutResearchPlan,
    ) -> list[SearchRun]:
        if request.query is None:
            raise HTTPException(status_code=400, detail="query is required")

        searches = research.searches or [
            InternetScoutResearchQuery(
                query=request.query,
                purpose="baseline",
                required=True,
            )
        ]
        per_query_count = (
            5
            if research.intent == "comparison"
            else (
                3
                if (len(searches) > 1 or research.provider_strategy == "fanout")
                else 5
            )
        )
        runs = await self._run_source_searches(
            request=request,
            research=research,
            count=per_query_count,
        )
        for search in searches[: research.max_searches]:
            responses = await self._search_with_provider_strategy(
                query=search.query,
                count=per_query_count,
                research=research,
            )
            runs.extend(
                SearchRun(
                    response=response,
                    purpose=search.purpose,
                    required=search.required,
                )
                for response in responses
            )
        return runs

    async def _run_source_searches(
        self,
        *,
        request: InternetScoutRequest,
        research: InternetScoutResearchPlan,
        count: int,
    ) -> list[SearchRun]:
        if request.query is None:
            return []
        assert_no_on_hold_data_sources(research.recommended_data_source_ids)
        data_source_ids = [
            data_source_id
            for data_source_id in dict.fromkeys(research.recommended_data_source_ids)
            if data_source_id in BEACON_EXECUTABLE_SOURCE_DATA_SOURCE_IDS
        ]
        if not data_source_ids:
            return []

        runs: list[SearchRun] = []
        for data_source_id in data_source_ids:
            try:
                response = await self.gateway_client.source_search(
                    data_source_id=data_source_id,
                    query=request.query,
                    count=count,
                )
            except InternetScoutGatewayError:
                logger.warning(
                    "BEACON_SOURCE_SEARCH_FALLBACK",
                    extra={
                        "event": "BEACON_SOURCE_SEARCH_FALLBACK",
                        "data_source_id": data_source_id,
                    },
                )
                continue
            if not response.results:
                continue
            runs.append(
                SearchRun(
                    response=response,
                    purpose=_source_search_purpose(data_source_id),
                    required=False,
                )
            )
        return runs

    async def _search_with_provider_strategy(
        self,
        *,
        query: str,
        count: int,
        research: InternetScoutResearchPlan,
    ) -> list[GatewaySearchResponse]:
        providers = research.search_providers or ["auto"]
        if research.provider_strategy != "fanout":
            return [
                await self.gateway_client.search(
                    query=query,
                    count=count,
                    provider=providers[0],
                )
            ]

        responses: list[GatewaySearchResponse] = []
        for provider in providers:
            try:
                responses.append(
                    await self.gateway_client.search(
                        query=query,
                        count=count,
                        provider=provider,
                    )
                )
            except InternetScoutGatewayError:
                continue
        if responses:
            return responses
        return [
            await self.gateway_client.search(
                query=query,
                count=count,
                provider="auto",
            )
        ]

    async def _extract_ranked_search_results(
        self,
        *,
        request: InternetScoutRequest,
        research: InternetScoutResearchPlan,
        search_runs: list[SearchRun],
    ) -> list[GatewayExtractResponse]:
        if research.max_extracts <= 0 or not search_runs:
            return []

        ranked = rank_search_results(
            request=request,
            runs=search_runs,
            max_results=research.max_extracts,
        )
        extract_responses: list[GatewayExtractResponse] = []
        for item in ranked:
            try:
                cached_extract = await self._cached_extract_response(
                    url=item.result.url,
                    query=request.query,
                )
                extract_responses.append(
                    cached_extract
                    if cached_extract is not None
                    else await self.gateway_client.extract(
                        url=item.result.url,
                        max_bytes=DEFAULT_MAX_CONTENT_BYTES,
                    )
                )
            except InternetScoutGatewayError:
                continue
        return extract_responses

    async def _cached_extract_response(
        self,
        *,
        url: str,
        query: str | None,
    ) -> GatewayExtractResponse | None:
        if self.web_cache_extract is None:
            return None
        try:
            return await self.web_cache_extract(url, query)
        except Exception as exc:
            logger.warning(
                "BEACON_WEB_CACHE_FALLBACK",
                extra={
                    "event": "BEACON_WEB_CACHE_FALLBACK",
                    "error_type": type(exc).__name__,
                },
            )
            return None


def _source_search_purpose(data_source_id: str) -> ResearchQueryPurpose:
    if data_source_id in {"pubmed-eutils", "sec-edgar", "osv-dev", "cisa-kev"}:
        return "primary_source"
    return "baseline"
