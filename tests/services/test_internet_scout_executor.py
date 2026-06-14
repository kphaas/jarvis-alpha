from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

import pytest

from brain.services.internet_scout.executor import InternetScoutExecutor
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
