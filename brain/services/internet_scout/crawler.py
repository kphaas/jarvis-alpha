"""Beacon crawler facade over existing Gateway fetch/extract/crawl egress."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from brain.services.internet_scout.evidence import (
    packet_from_crawl_response,
    packet_from_extract_response,
)
from brain.services.internet_scout.gateway_client import InternetScoutGatewayClient
from brain.services.internet_scout.models import (
    GatewayCrawlPage,
    GatewayCrawlResponse,
    GatewayExtractResponse,
    InternetEvidencePacket,
    InternetScoutCrawlerCrawlRequest,
    InternetScoutCrawlerExtractRequest,
    InternetScoutCrawlerExtractResponse,
    InternetScoutCrawlerFieldEvidence,
    InternetScoutCrawlerMapRequest,
    InternetScoutCrawlerMapResponse,
    InternetScoutCrawlerPage,
    InternetScoutCrawlerScrapeRequest,
    InternetScoutCrawlerScrapeResponse,
    InternetScoutRequest,
)
from brain.services.internet_scout.policy import (
    CRAWL_MAX_DEPTH_WITHOUT_APPROVAL,
    CRAWL_MAX_PAGES_WITHOUT_APPROVAL,
)

CacheLookup = Callable[[str, str | None], Awaitable[GatewayExtractResponse | None]]


class InternetScoutCrawler:
    """Small crawler contract; Gateway still owns network egress and parsing."""

    def __init__(
        self, gateway_client: InternetScoutGatewayClient | None = None
    ) -> None:
        self.gateway_client = gateway_client or InternetScoutGatewayClient()

    async def scrape(
        self,
        body: InternetScoutCrawlerScrapeRequest,
        request_id,
        scout_request: InternetScoutRequest,
        *,
        cache_lookup: CacheLookup | None = None,
    ) -> tuple[
        InternetScoutCrawlerScrapeResponse, InternetEvidencePacket, dict[str, object]
    ]:
        cached = (
            None
            if body.force_refresh or cache_lookup is None
            else await cache_lookup(body.url, body.query)
        )
        if cached is not None:
            packet = packet_from_extract_response(
                request=scout_request, response=cached
            )
            return (
                _scrape_response_from_extract(
                    request_id=request_id,
                    response=cached,
                    cache_hit=True,
                ),
                packet,
                _metadata("scrape", cache_hit=True, page_count=1, packet=packet),
            )

        crawl = await self.gateway_client.crawl(
            url=body.url,
            max_pages=1,
            max_depth=0,
            max_bytes=body.max_bytes,
        )
        packet = packet_from_crawl_response(request=scout_request, response=crawl)
        page = crawl.pages[0] if crawl.pages else None
        if page is None:
            return (
                InternetScoutCrawlerScrapeResponse(
                    request_id=request_id,
                    canonical_url=crawl.seed_url,
                    host=crawl.seed_host,
                    fetched_at=crawl.fetched_at,
                    text="",
                    content_hash="0" * 64,
                ),
                packet,
                _metadata("scrape", cache_hit=False, page_count=0, packet=packet),
            )
        return (
            _scrape_response_from_page(request_id=request_id, page=page),
            packet,
            _metadata("scrape", cache_hit=False, page_count=1, packet=packet),
        )

    async def map(
        self,
        body: InternetScoutCrawlerMapRequest,
        request_id,
        scout_request: InternetScoutRequest,
    ) -> tuple[
        InternetScoutCrawlerMapResponse, InternetEvidencePacket, dict[str, object]
    ]:
        crawl = await self.gateway_client.crawl(
            url=body.url,
            max_pages=body.max_pages,
            max_depth=body.max_depth,
            max_bytes=body.max_bytes,
        )
        packet = packet_from_crawl_response(request=scout_request, response=crawl)
        response = _map_response_from_crawl(request_id=request_id, crawl=crawl)
        return (
            response,
            packet,
            _metadata(
                "map",
                cache_hit=False,
                page_count=len(crawl.pages),
                packet=packet,
                link_count=response.link_count,
                max_pages=crawl.max_pages,
                max_depth=crawl.max_depth,
                page_cap_hit=_page_cap_hit(crawl),
                depth_cap_hit=_depth_cap_hit(crawl),
            ),
        )

    async def crawl(
        self,
        body: InternetScoutCrawlerCrawlRequest,
        request_id,
        scout_request: InternetScoutRequest,
    ) -> tuple[
        InternetScoutCrawlerMapResponse, InternetEvidencePacket, dict[str, object]
    ]:
        response, packet, metadata = await self.map(body, request_id, scout_request)
        metadata["operation"] = "crawl"
        return response, packet, metadata

    async def extract(
        self,
        body: InternetScoutCrawlerExtractRequest,
        request_id,
        scout_request: InternetScoutRequest,
        *,
        cache_lookup: CacheLookup | None = None,
    ) -> tuple[
        InternetScoutCrawlerExtractResponse, InternetEvidencePacket, dict[str, object]
    ]:
        scrape, packet, metadata = await self.scrape(
            body,
            request_id,
            scout_request,
            cache_lookup=cache_lookup,
        )
        fields = _extract_fields(
            text=scrape.text,
            schema=body.extract_schema,
            source_url=scrape.canonical_url,
        )
        metadata.update(
            {
                "operation": "extract",
                "schema_field_count": len(body.extract_schema),
                "matched_field_count": sum(1 for field in fields if field.found),
            }
        )
        return (
            InternetScoutCrawlerExtractResponse(
                request_id=request_id,
                cache_hit=scrape.cache_hit,
                canonical_url=scrape.canonical_url,
                host=scrape.host,
                fetched_at=scrape.fetched_at,
                fields=fields,
            ),
            packet,
            metadata,
        )


def _scrape_response_from_extract(
    *,
    request_id,
    response: GatewayExtractResponse,
    cache_hit: bool,
) -> InternetScoutCrawlerScrapeResponse:
    return InternetScoutCrawlerScrapeResponse(
        request_id=request_id,
        cache_hit=cache_hit,
        canonical_url=response.url,
        host=response.host,
        fetched_at=response.fetched_at,
        text=response.extracted_text[:5000],
        links=[],
        content_hash=response.content_hash,
        risk_markers=response.risk_markers,
    )


def _scrape_response_from_page(
    *,
    request_id,
    page: GatewayCrawlPage,
) -> InternetScoutCrawlerScrapeResponse:
    return InternetScoutCrawlerScrapeResponse(
        request_id=request_id,
        cache_hit=False,
        canonical_url=page.url,
        host=page.host,
        fetched_at=page.fetched_at,
        text=page.extracted_text[:5000],
        links=page.discovered_links,
        content_hash=page.content_hash,
        risk_markers=page.risk_markers,
    )


def _map_response_from_crawl(
    *,
    request_id,
    crawl,
) -> InternetScoutCrawlerMapResponse:
    links = list(
        dict.fromkeys(link for page in crawl.pages for link in page.discovered_links)
    )
    return InternetScoutCrawlerMapResponse(
        request_id=request_id,
        seed_url=crawl.seed_url,
        seed_host=crawl.seed_host,
        page_count=len(crawl.pages),
        link_count=len(links),
        max_pages=crawl.max_pages,
        max_depth=crawl.max_depth,
        pages=[
            InternetScoutCrawlerPage(
                url=page.url,
                host=page.host,
                depth=page.depth,
                status_code=page.status_code,
                fetched_at=page.fetched_at,
                content_hash=page.content_hash,
                text=page.extracted_text[:5000],
                links=page.discovered_links,
                extractor=page.extractor,
                truncated=page.truncated,
                risk_markers=page.risk_markers,
            )
            for page in crawl.pages
        ],
        links=links[:250],
    )


def _extract_fields(
    *,
    text: str,
    schema: dict[str, str],
    source_url: str,
) -> list[InternetScoutCrawlerFieldEvidence]:
    clean_schema = {
        str(field).strip()[:80]: str(hint).strip()[:160]
        for field, hint in schema.items()
        if str(field).strip()
    }
    return [
        _extract_field(field=field, hint=hint, text=text, source_url=source_url)
        for field, hint in clean_schema.items()
    ]


def _extract_field(
    *,
    field: str,
    hint: str,
    text: str,
    source_url: str,
) -> InternetScoutCrawlerFieldEvidence:
    terms = _terms(field, hint)
    for match in re.finditer(r"[^.\n]{0,220}(?:\.|\n|$)", text):
        snippet = " ".join(match.group(0).split())
        if not snippet:
            continue
        lower = snippet.lower()
        if any(term in lower for term in terms):
            return InternetScoutCrawlerFieldEvidence(
                field=field,
                found=True,
                value=snippet[:500],
                source_url=source_url,
                evidence_text=snippet[:500],
                start_char=match.start(),
                end_char=match.end(),
            )
    return InternetScoutCrawlerFieldEvidence(field=field, source_url=source_url)


def _terms(*values: str) -> tuple[str, ...]:
    terms: list[str] = []
    for value in values:
        for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", value.lower()):
            if token not in terms:
                terms.append(token)
    return tuple(terms or [""])


def _page_cap_hit(crawl: GatewayCrawlResponse) -> bool:
    return (
        crawl.max_pages >= CRAWL_MAX_PAGES_WITHOUT_APPROVAL
        and len(crawl.pages) >= crawl.max_pages
    )


def _depth_cap_hit(crawl: GatewayCrawlResponse) -> bool:
    return crawl.max_depth >= CRAWL_MAX_DEPTH_WITHOUT_APPROVAL and any(
        page.depth >= crawl.max_depth for page in crawl.pages
    )


def _metadata(
    operation: str,
    *,
    cache_hit: bool,
    page_count: int,
    packet: InternetEvidencePacket,
    link_count: int = 0,
    max_pages: int | None = None,
    max_depth: int | None = None,
    page_cap_hit: bool = False,
    depth_cap_hit: bool = False,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "operation": operation,
        "cache_hit": cache_hit,
        "page_count": page_count,
        "link_count": link_count,
        "source_count": len(packet.sources),
        "claim_count": len(packet.claims),
        "same_host_required": True,
        "forms_allowed": False,
        "credential_entry_allowed": False,
        "raw_web_content_included": False,
        "raw_web_content_is_untrusted": True,
    }
    if max_pages is not None:
        metadata["max_pages"] = max_pages
        metadata["page_cap_hit"] = page_cap_hit
    if max_depth is not None:
        metadata["max_depth"] = max_depth
        metadata["depth_cap_hit"] = depth_cap_hit
    metadata["time_cap_hit"] = False
    metadata["cap_pressure"] = page_cap_hit or depth_cap_hit
    return metadata
