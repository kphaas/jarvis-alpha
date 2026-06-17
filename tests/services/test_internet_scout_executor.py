from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

import pytest

from brain.services.internet_scout.executor import InternetScoutExecutor
from brain.services.internet_scout.free_source_router import FreeSourceRouter
from brain.services.internet_scout.gateway_client import (
    InternetScoutGatewayClient,
    InternetScoutGatewayError,
)
from brain.services.internet_scout.models import (
    GatewayCrawlResponse,
    GatewayExtractResponse,
    GatewaySearchResponse,
    InternetScoutRequest,
    InternetTool,
)
from brain.services.internet_scout.orchestrator import InternetScoutOrchestrator


class FakeGatewayClient(InternetScoutGatewayClient):
    def __init__(self) -> None:
        self.search_calls: list[dict[str, object]] = []
        self.extract_calls: list[dict[str, object]] = []
        self.crawl_calls: list[dict[str, object]] = []

    async def search(
        self,
        *,
        query: str,
        count: int = 5,
        provider: str = "auto",
    ) -> GatewaySearchResponse:
        self.search_calls.append({"query": query, "count": count, "provider": provider})
        call_index = len(self.search_calls)
        host = (
            f"{provider}.example.test" if provider != "auto" else "public.example.test"
        )
        return GatewaySearchResponse(
            provider=provider,
            query_hash="a" * 64,
            fetched_at=datetime(2026, 6, 6, 13, 0, tzinfo=UTC),
            results=[
                {
                    "title": f"Result {call_index}",
                    "url": f"https://{host}/result-{call_index}",
                    "host": host,
                    "description": f"Beacon search result {call_index}.",
                    "risk_markers": [],
                }
            ],
        )

    async def fetch(self, *, url: str, max_bytes: int):
        raise AssertionError("fetch should not be called for extract requests")

    async def extract(self, *, url: str, max_bytes: int) -> GatewayExtractResponse:
        self.extract_calls.append({"url": url, "max_bytes": max_bytes})
        host = urlparse(url).hostname or "public.example.test"
        return GatewayExtractResponse(
            url=url,
            host=host,
            status_code=200,
            content_type="text/html",
            content_hash="d" * 64,
            fetched_at=datetime(2026, 6, 6, 13, 0, tzinfo=UTC),
            extracted_text=f"Beacon extracted body from {host}.",
            extractor="trafilatura",
            extraction_fallback=False,
            truncated=False,
            risk_markers=[],
            redirect_chain=[url],
        )

    async def crawl(
        self,
        *,
        url: str,
        max_pages: int,
        max_depth: int,
        max_bytes: int,
    ) -> GatewayCrawlResponse:
        self.crawl_calls.append(
            {
                "url": url,
                "max_pages": max_pages,
                "max_depth": max_depth,
                "max_bytes": max_bytes,
            }
        )
        return GatewayCrawlResponse(
            seed_url="https://public.example.test/start",
            seed_host="public.example.test",
            fetched_at=datetime(2026, 6, 6, 13, 0, tzinfo=UTC),
            max_pages=max_pages,
            max_depth=max_depth,
            pages=[
                {
                    "url": "https://public.example.test/start",
                    "host": "public.example.test",
                    "depth": 0,
                    "status_code": 200,
                    "content_type": "text/html",
                    "content_hash": "e" * 64,
                    "fetched_at": datetime(2026, 6, 6, 13, 0, tzinfo=UTC),
                    "extracted_text": "Beacon crawled page.",
                    "extractor": "trafilatura",
                    "extraction_fallback": False,
                    "truncated": False,
                    "risk_markers": [],
                    "redirect_chain": ["https://public.example.test/start"],
                    "discovered_links": ["https://public.example.test/next"],
                }
            ],
        )


class FailingFanoutGatewayClient(FakeGatewayClient):
    async def search(
        self,
        *,
        query: str,
        count: int = 5,
        provider: str = "auto",
    ) -> GatewaySearchResponse:
        if provider in {"brave", "perplexity"}:
            self.search_calls.append(
                {"query": query, "count": count, "provider": provider}
            )
            raise InternetScoutGatewayError(f"{provider} unavailable")
        return await super().search(query=query, count=count, provider=provider)


async def fake_weather_client(params: dict[str, object]) -> dict[str, object]:
    return {
        "status": "ok",
        "provider": "open-meteo",
        "location_label": params.get("location_label") or "home",
        "observed_at": "2026-06-17T13:00",
        "latitude": 40.0,
        "longitude": -75.0,
        "temperature_f": 72.4,
        "apparent_temperature_f": 73.1,
        "relative_humidity_pct": 51,
        "precipitation_in": 0,
        "weather_code": 1,
        "condition": "mostly clear",
        "cloud_cover_pct": 10,
        "wind_speed_mph": 6.2,
        "wind_gust_mph": 11.0,
        "cached": False,
    }


async def failing_weather_client(_params: dict[str, object]) -> dict[str, object]:
    raise RuntimeError("weather adapter unavailable")


class ComparisonCoverageGatewayClient(FakeGatewayClient):
    async def search(
        self,
        *,
        query: str,
        count: int = 5,
        provider: str = "auto",
    ) -> GatewaySearchResponse:
        self.search_calls.append({"query": query, "count": count, "provider": provider})
        results = [
            {
                "title": "OpenAI Responses API",
                "url": "https://platform.openai.com/docs/api-reference/responses",
                "host": "platform.openai.com",
                "description": "The OpenAI Responses API reference is on platform.openai.com.",
                "risk_markers": [],
            },
            {
                "title": "OpenAI API reference",
                "url": "https://platform.openai.com/docs/api-reference",
                "host": "platform.openai.com",
                "description": "The OpenAI API reference is on platform.openai.com.",
                "risk_markers": [],
            },
        ]
        if "anthropic" in query.lower():
            results.insert(
                1,
                {
                    "title": "Anthropic Messages API",
                    "url": "https://docs.anthropic.com/en/api/messages",
                    "host": "docs.anthropic.com",
                    "description": "The Anthropic Messages API documentation is on docs.anthropic.com.",
                    "risk_markers": [],
                },
            )
        return GatewaySearchResponse(
            provider=provider,
            query_hash="a" * 64,
            fetched_at=datetime(2026, 6, 16, 13, 0, tzinfo=UTC),
            results=results[:count],
        )


class MultiSourceComparisonCoverageGatewayClient(FakeGatewayClient):
    async def search(
        self,
        *,
        query: str,
        count: int = 5,
        provider: str = "auto",
    ) -> GatewaySearchResponse:
        self.search_calls.append({"query": query, "count": count, "provider": provider})
        normalized = query.lower()
        if "brave search api" in normalized:
            results = [
                {
                    "title": "Brave Search pricing",
                    "url": "https://brave.com/search/api/pricing",
                    "host": "brave.com",
                    "description": "Brave Search API pricing.",
                    "risk_markers": [],
                },
                {
                    "title": "Brave overview",
                    "url": "https://brave.com/search/api",
                    "host": "brave.com",
                    "description": "Brave Search API overview.",
                    "risk_markers": [],
                },
                {
                    "title": "Firecrawl comparison",
                    "url": "https://www.firecrawl.dev/blog/brave-vs-perplexity",
                    "host": "www.firecrawl.dev",
                    "description": "Third-party comparison of Brave and Perplexity APIs.",
                    "risk_markers": [],
                },
            ]
        elif "perplexity api" in normalized:
            results = [
                {
                    "title": "Firecrawl comparison",
                    "url": "https://www.firecrawl.dev/blog/brave-vs-perplexity",
                    "host": "www.firecrawl.dev",
                    "description": "Third-party comparison of Brave and Perplexity APIs.",
                    "risk_markers": [],
                },
                {
                    "title": "Perplexity marketing",
                    "url": "https://www.perplexity.ai/hub/blog/search-api",
                    "host": "www.perplexity.ai",
                    "description": "Perplexity Search API blog overview.",
                    "risk_markers": [],
                },
                {
                    "title": "General roundup",
                    "url": "https://example.test/perplexity-roundup",
                    "host": "example.test",
                    "description": "Third-party roundup mentioning Perplexity.",
                    "risk_markers": [],
                },
                {
                    "title": "Perplexity Search API docs",
                    "url": "https://docs.perplexity.ai/guides/search-api",
                    "host": "docs.perplexity.ai",
                    "description": "Perplexity Search API documentation.",
                    "risk_markers": [],
                },
            ]
        else:
            results = [
                {
                    "title": "Brave Search API",
                    "url": "https://brave.com/search/api",
                    "host": "brave.com",
                    "description": "Brave Search API overview.",
                    "risk_markers": [],
                },
                {
                    "title": "Perplexity Search API",
                    "url": "https://docs.perplexity.ai/guides/search-api",
                    "host": "docs.perplexity.ai",
                    "description": "Perplexity Search API documentation.",
                    "risk_markers": [],
                },
            ]
        return GatewaySearchResponse(
            provider=provider,
            query_hash="b" * 64,
            fetched_at=datetime(2026, 6, 16, 13, 0, tzinfo=UTC),
            results=results[:count],
        )


@pytest.mark.asyncio
async def test_executor_routes_current_weather_to_free_source_before_search():
    gateway = FakeGatewayClient()
    executor = InternetScoutExecutor(
        gateway_client=gateway,
        free_source_router=FreeSourceRouter(weather_client=fake_weather_client),
    )

    decision, packet = await executor.execute(
        InternetScoutRequest(
            query="what is the weather outside right now?",
            tool_hint=InternetTool.SEARCH,
        )
    )

    assert decision.tool == InternetTool.SEARCH
    assert gateway.search_calls == []
    assert packet.sources[0].host == "open-meteo.com"
    assert packet.sources[0].title == "Open-Meteo current weather via Alpha Gateway"
    assert "mostly clear" in packet.claims[0].citation_text
    assert "72F" in packet.claims[0].citation_text


@pytest.mark.asyncio
async def test_executor_does_not_free_route_weather_with_explicit_location():
    gateway = FakeGatewayClient()
    executor = InternetScoutExecutor(
        gateway_client=gateway,
        free_source_router=FreeSourceRouter(weather_client=fake_weather_client),
    )

    decision, packet = await executor.execute(
        InternetScoutRequest(
            query="what is the weather in Chicago right now?",
            tool_hint=InternetTool.SEARCH,
        )
    )

    assert decision.tool == InternetTool.SEARCH
    assert gateway.search_calls == [
        {
            "query": "what is the weather in Chicago right now?",
            "count": 5,
            "provider": "auto",
        }
    ]
    assert packet.sources[0].host == "public.example.test"


@pytest.mark.asyncio
async def test_executor_falls_back_to_search_when_free_weather_fails():
    gateway = FakeGatewayClient()
    executor = InternetScoutExecutor(
        gateway_client=gateway,
        free_source_router=FreeSourceRouter(weather_client=failing_weather_client),
    )

    decision, packet = await executor.execute(
        InternetScoutRequest(
            query="current temperature outside",
            tool_hint=InternetTool.SEARCH,
        )
    )

    assert decision.tool == InternetTool.SEARCH
    assert gateway.search_calls == [
        {
            "query": "current temperature outside",
            "count": 5,
            "provider": "auto",
        }
    ]
    assert packet.sources[0].host == "public.example.test"


@pytest.mark.asyncio
async def test_executor_uses_extract_gateway_path_for_extract_tool():
    gateway = FakeGatewayClient()
    executor = InternetScoutExecutor(gateway_client=gateway)

    decision, packet = await executor.execute(
        InternetScoutRequest(
            urls=["https://public.example.test/report"],
            tool_hint=InternetTool.EXTRACT,
        )
    )

    assert decision.tool == InternetTool.EXTRACT
    assert gateway.extract_calls == [
        {
            "url": "https://public.example.test/report",
            "max_bytes": 1_000_000,
        }
    ]
    assert packet.claims[0].citation_text == (
        "Beacon extracted body from public.example.test."
    )


@pytest.mark.asyncio
async def test_executor_uses_research_plan_for_deep_search():
    gateway = FakeGatewayClient()
    executor = InternetScoutExecutor(gateway_client=gateway)
    request = InternetScoutRequest(
        query="Find the official OpenAI API reference URL",
        tool_hint=InternetTool.SEARCH,
        max_pages=4,
        requester="alpha_chat.deep_research",
    )
    plan = InternetScoutOrchestrator().plan(request)

    decision, packet = await executor.execute(request, plan=plan)

    assert decision.tool == InternetTool.SEARCH
    assert plan.research.provider_strategy == "fanout"
    assert plan.research.search_providers == ["brave", "perplexity"]
    assert plan.research.max_extracts == 4
    assert len(gateway.search_calls) == (
        len(plan.research.searches) * len(plan.research.search_providers)
    )
    assert all(call["count"] == 3 for call in gateway.search_calls)
    assert {call["provider"] for call in gateway.search_calls} == {
        "brave",
        "perplexity",
    }
    assert len(gateway.extract_calls) == plan.research.max_extracts
    assert packet.request == request
    assert packet.claims[0].citation_text.startswith("Beacon extracted body")
    assert all(
        "search result" not in claim.citation_text for claim in packet.claims[:4]
    )


@pytest.mark.asyncio
async def test_executor_extracts_official_comparison_vendor_coverage():
    gateway = ComparisonCoverageGatewayClient()
    executor = InternetScoutExecutor(gateway_client=gateway)
    request = InternetScoutRequest(
        query=(
            "Compare the OpenAI Responses API and Anthropic Messages API for "
            "building a chat gateway. Use official vendor docs only and cite them."
        ),
        tool_hint=InternetTool.SEARCH,
        max_pages=4,
        requester="alpha_chat.deep_research",
    )
    plan = InternetScoutOrchestrator().plan(request)

    decision, packet = await executor.execute(request, plan=plan)

    assert decision.tool == InternetTool.SEARCH
    extracted_hosts = {urlparse(call["url"]).hostname for call in gateway.extract_calls}
    assert "platform.openai.com" in extracted_hosts
    assert "docs.anthropic.com" in extracted_hosts
    assert {"platform.openai.com", "docs.anthropic.com"} <= {
        source.host for source in packet.sources
    }


@pytest.mark.asyncio
async def test_executor_uses_deeper_result_window_for_multi_source_comparison():
    gateway = MultiSourceComparisonCoverageGatewayClient()
    executor = InternetScoutExecutor(gateway_client=gateway)
    request = InternetScoutRequest(
        query=(
            "Compare Brave Search API and Perplexity API for building an AI web "
            "research agent. Cite independent sources."
        ),
        tool_hint=InternetTool.SEARCH,
        max_pages=4,
        requester="alpha_chat.deep_research",
    )
    plan = InternetScoutOrchestrator().plan(request)

    decision, packet = await executor.execute(request, plan=plan)

    assert decision.tool == InternetTool.SEARCH
    assert plan.research.intent == "comparison"
    assert all(call["count"] == 5 for call in gateway.search_calls)
    extracted_hosts = {urlparse(call["url"]).hostname for call in gateway.extract_calls}
    assert "docs.perplexity.ai" in extracted_hosts
    assert {"brave.com", "docs.perplexity.ai"} <= {
        source.host for source in packet.sources
    }


@pytest.mark.asyncio
async def test_executor_falls_back_to_auto_when_fanout_providers_fail():
    gateway = FailingFanoutGatewayClient()
    executor = InternetScoutExecutor(gateway_client=gateway)
    request = InternetScoutRequest(
        query="latest Alpha production status",
        tool_hint=InternetTool.SEARCH,
        max_pages=4,
        requester="alpha_chat.deep_research",
    )
    plan = InternetScoutOrchestrator().plan(request)

    decision, packet = await executor.execute(request, plan=plan)

    assert decision.tool == InternetTool.SEARCH
    assert any(call["provider"] == "auto" for call in gateway.search_calls)
    assert packet.sources
    assert packet.claims[0].citation_text.startswith("Beacon extracted body")


@pytest.mark.asyncio
async def test_executor_uses_crawl_gateway_path_for_bounded_crawl():
    gateway = FakeGatewayClient()
    executor = InternetScoutExecutor(gateway_client=gateway)

    decision, packet = await executor.execute(
        InternetScoutRequest(
            urls=["https://public.example.test/start"],
            tool_hint=InternetTool.CRAWL,
            max_pages=3,
            max_depth=1,
        )
    )

    assert decision.tool == InternetTool.CRAWL
    assert gateway.crawl_calls == [
        {
            "url": "https://public.example.test/start",
            "max_pages": 3,
            "max_depth": 1,
            "max_bytes": 1_000_000,
        }
    ]
    assert packet.sources[0].url == "https://public.example.test/start"
    assert packet.claims[0].citation_text == "Beacon crawled page."
