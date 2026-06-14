from __future__ import annotations

from datetime import UTC, datetime

import pytest

from brain.services.internet_scout.executor import InternetScoutExecutor
from brain.services.internet_scout.gateway_client import InternetScoutGatewayClient
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

    async def search(self, *, query: str, count: int = 5) -> GatewaySearchResponse:
        self.search_calls.append({"query": query, "count": count})
        call_index = len(self.search_calls)
        return GatewaySearchResponse(
            provider="fake",
            query_hash="a" * 64,
            fetched_at=datetime(2026, 6, 6, 13, 0, tzinfo=UTC),
            results=[
                {
                    "title": f"Result {call_index}",
                    "url": f"https://public.example.test/result-{call_index}",
                    "host": "public.example.test",
                    "description": f"Beacon search result {call_index}.",
                    "risk_markers": [],
                }
            ],
        )

    async def fetch(self, *, url: str, max_bytes: int):
        raise AssertionError("fetch should not be called for extract requests")

    async def extract(self, *, url: str, max_bytes: int) -> GatewayExtractResponse:
        self.extract_calls.append({"url": url, "max_bytes": max_bytes})
        return GatewayExtractResponse(
            url="https://public.example.test/report",
            host="public.example.test",
            status_code=200,
            content_type="text/html",
            content_hash="d" * 64,
            fetched_at=datetime(2026, 6, 6, 13, 0, tzinfo=UTC),
            extracted_text="Beacon extracted body.",
            extractor="trafilatura",
            extraction_fallback=False,
            truncated=False,
            risk_markers=[],
            redirect_chain=["https://public.example.test/report"],
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
    assert packet.claims[0].citation_text == "Beacon extracted body."


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
    assert len(gateway.search_calls) == len(plan.research.searches)
    assert all(call["count"] == 3 for call in gateway.search_calls)
    assert packet.request == request
    assert len(packet.sources) == len(plan.research.searches)
    assert packet.claims[0].citation_text == "Beacon search result 1."


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
