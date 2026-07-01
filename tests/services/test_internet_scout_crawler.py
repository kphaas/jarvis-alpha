from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from brain.services.internet_scout.crawler import InternetScoutCrawler
from brain.services.internet_scout.models import (
    GatewayCrawlResponse,
    GatewayExtractResponse,
    InternetScoutCrawlerCrawlRequest,
    InternetScoutCrawlerExtractRequest,
    InternetScoutCrawlerScrapeRequest,
    InternetScoutRequest,
    InternetTool,
)
from brain.services.internet_scout.policy import (
    CRAWL_MAX_DEPTH_WITHOUT_APPROVAL,
    CRAWL_MAX_PAGES_WITHOUT_APPROVAL,
)


class FakeGateway:
    def __init__(self, *, page_count: int = 1, page_depth: int = 0) -> None:
        self.crawl_calls: list[dict[str, object]] = []
        self.page_count = page_count
        self.page_depth = page_depth

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
            seed_url=url,
            seed_host="public.example.test",
            fetched_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
            max_pages=max_pages,
            max_depth=max_depth,
            pages=[
                {
                    "url": url
                    if index == 0
                    else f"https://public.example.test/page-{index}",
                    "host": "public.example.test",
                    "depth": self.page_depth,
                    "status_code": 200,
                    "content_type": "text/html",
                    "content_hash": "a" * 64,
                    "fetched_at": datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
                    "extracted_text": (
                        "Pricing is $20 per month. The product launched in 2026."
                    ),
                    "extractor": "trafilatura",
                    "extraction_fallback": False,
                    "truncated": False,
                    "risk_markers": [],
                    "redirect_chain": [url],
                    "discovered_links": ["https://public.example.test/docs"],
                }
                for index in range(self.page_count)
            ],
        )


@pytest.mark.asyncio
async def test_crawler_scrape_reuses_cache_before_gateway() -> None:
    gateway = FakeGateway()
    crawler = InternetScoutCrawler(gateway)
    cached = GatewayExtractResponse(
        url="https://public.example.test/report",
        host="public.example.test",
        status_code=200,
        content_type="text/plain",
        content_hash="b" * 64,
        fetched_at=datetime(2026, 6, 30, 11, 0, tzinfo=UTC),
        extracted_text="Cached crawler body.",
        extractor="beacon_web_cache",
        extraction_fallback=False,
        truncated=True,
        risk_markers=["web_cache_hit"],
        redirect_chain=["https://public.example.test/report"],
    )

    async def cache_lookup(url: str, query: str | None):
        assert url == "https://public.example.test/report"
        assert query == "beacon"
        return cached

    response, packet, metadata = await crawler.scrape(
        InternetScoutCrawlerScrapeRequest(
            url="https://public.example.test/report",
            query="beacon",
        ),
        uuid4(),
        InternetScoutRequest(
            query="beacon",
            urls=["https://public.example.test/report"],
            tool_hint=InternetTool.EXTRACT,
        ),
        cache_lookup=cache_lookup,
    )

    assert response.cache_hit is True
    assert response.text == "Cached crawler body."
    assert packet.claims[0].citation_text == "Cached crawler body."
    assert metadata["cache_hit"] is True
    assert gateway.crawl_calls == []


@pytest.mark.asyncio
async def test_crawler_crawl_returns_links_and_evidence_metadata() -> None:
    gateway = FakeGateway()
    crawler = InternetScoutCrawler(gateway)

    response, packet, metadata = await crawler.crawl(
        InternetScoutCrawlerCrawlRequest(
            url="https://public.example.test/report",
            max_pages=3,
            max_depth=1,
        ),
        uuid4(),
        InternetScoutRequest(
            urls=["https://public.example.test/report"],
            tool_hint=InternetTool.CRAWL,
            max_pages=3,
            max_depth=1,
        ),
    )

    assert response.page_count == 1
    assert response.links == ["https://public.example.test/docs"]
    assert packet.sources[0].host == "public.example.test"
    assert metadata["operation"] == "crawl"
    assert metadata["source_count"] == 1
    assert metadata["max_pages"] == 3
    assert metadata["max_depth"] == 1
    assert metadata["page_cap_hit"] is False
    assert metadata["depth_cap_hit"] is False
    assert metadata["time_cap_hit"] is False
    assert metadata["cap_pressure"] is False
    assert gateway.crawl_calls[0]["max_pages"] == 3
    assert gateway.crawl_calls[0]["max_depth"] == 1


@pytest.mark.asyncio
async def test_crawler_tiny_smoke_bounds_do_not_create_cap_pressure() -> None:
    crawler = InternetScoutCrawler(FakeGateway(page_count=1))

    _response, _packet, metadata = await crawler.crawl(
        InternetScoutCrawlerCrawlRequest(
            url="https://public.example.test/report",
            max_pages=1,
            max_depth=0,
        ),
        uuid4(),
        InternetScoutRequest(
            urls=["https://public.example.test/report"],
            tool_hint=InternetTool.CRAWL,
            max_pages=1,
            max_depth=0,
        ),
    )

    assert metadata["page_cap_hit"] is False
    assert metadata["depth_cap_hit"] is False
    assert metadata["cap_pressure"] is False


@pytest.mark.asyncio
async def test_crawler_safety_ceiling_hit_creates_cap_pressure() -> None:
    crawler = InternetScoutCrawler(
        FakeGateway(
            page_count=CRAWL_MAX_PAGES_WITHOUT_APPROVAL,
            page_depth=CRAWL_MAX_DEPTH_WITHOUT_APPROVAL,
        )
    )

    _response, _packet, metadata = await crawler.crawl(
        InternetScoutCrawlerCrawlRequest(
            url="https://public.example.test/report",
            max_pages=CRAWL_MAX_PAGES_WITHOUT_APPROVAL,
            max_depth=CRAWL_MAX_DEPTH_WITHOUT_APPROVAL,
        ),
        uuid4(),
        InternetScoutRequest(
            urls=["https://public.example.test/report"],
            tool_hint=InternetTool.CRAWL,
            max_pages=CRAWL_MAX_PAGES_WITHOUT_APPROVAL,
            max_depth=CRAWL_MAX_DEPTH_WITHOUT_APPROVAL,
        ),
    )

    assert metadata["page_cap_hit"] is True
    assert metadata["depth_cap_hit"] is True
    assert metadata["cap_pressure"] is True


@pytest.mark.asyncio
async def test_crawler_extract_returns_field_evidence_spans() -> None:
    crawler = InternetScoutCrawler(FakeGateway())

    response, _packet, metadata = await crawler.extract(
        InternetScoutCrawlerExtractRequest(
            url="https://public.example.test/report",
            schema={"pricing": "monthly price", "launch": "launch date"},
        ),
        uuid4(),
        InternetScoutRequest(
            urls=["https://public.example.test/report"],
            tool_hint=InternetTool.EXTRACT,
        ),
    )

    assert response.fields[0].field == "pricing"
    assert response.fields[0].found is True
    assert "Pricing is $20" in str(response.fields[0].evidence_text)
    assert response.fields[0].start_char == 0
    assert response.fields[1].field == "launch"
    assert response.fields[1].found is True
    assert metadata["schema_field_count"] == 2
    assert metadata["matched_field_count"] == 2
