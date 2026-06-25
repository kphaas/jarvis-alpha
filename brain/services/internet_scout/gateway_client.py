"""Brain client for Beacon Gateway egress endpoints."""

from __future__ import annotations

from brain.services.gateway_egress import GatewayEgressError, call_gateway_proxy
from brain.services.internet_scout.models import (
    GatewayCrawlResponse,
    GatewayExtractResponse,
    GatewayFetchResponse,
    GatewaySearchResponse,
    SearchProvider,
)


class InternetScoutGatewayError(RuntimeError):
    pass


class InternetScoutGatewayClient:
    """Call Gateway-owned public internet endpoints from Brain."""

    async def health(self) -> dict[str, object]:
        try:
            payload = await call_gateway_proxy(
                "internet/health",
                {},
                timeout_s=10,
            )
        except GatewayEgressError as exc:
            raise InternetScoutGatewayError(
                f"Beacon gateway health failed: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise InternetScoutGatewayError(
                "Beacon gateway health returned invalid JSON"
            )
        return dict(payload)

    async def search(
        self,
        *,
        query: str,
        count: int = 5,
        provider: SearchProvider = "auto",
    ) -> GatewaySearchResponse:
        try:
            payload = await call_gateway_proxy(
                "internet/search",
                {"query": query, "count": count, "provider": provider},
                timeout_s=25,
            )
        except GatewayEgressError as exc:
            raise InternetScoutGatewayError(f"Beacon search failed: {exc}") from exc
        return GatewaySearchResponse.model_validate(payload)

    async def source_search(
        self,
        *,
        data_source_id: str,
        query: str,
        count: int = 5,
    ) -> GatewaySearchResponse:
        try:
            payload = await call_gateway_proxy(
                "internet/source-search",
                {
                    "data_source_id": data_source_id,
                    "query": query,
                    "count": count,
                },
                timeout_s=25,
            )
        except GatewayEgressError as exc:
            raise InternetScoutGatewayError(
                f"Beacon source search failed: {exc}"
            ) from exc
        return GatewaySearchResponse.model_validate(payload)

    async def fetch(
        self,
        *,
        url: str,
        max_bytes: int,
    ) -> GatewayFetchResponse:
        try:
            payload = await call_gateway_proxy(
                "internet/fetch",
                {"url": url, "max_bytes": max_bytes},
                timeout_s=35,
            )
        except GatewayEgressError as exc:
            raise InternetScoutGatewayError(f"Beacon fetch failed: {exc}") from exc
        return GatewayFetchResponse.model_validate(payload)

    async def extract(
        self,
        *,
        url: str,
        max_bytes: int,
    ) -> GatewayExtractResponse:
        try:
            payload = await call_gateway_proxy(
                "internet/extract",
                {"url": url, "max_bytes": max_bytes},
                timeout_s=40,
            )
        except GatewayEgressError as exc:
            raise InternetScoutGatewayError(f"Beacon extraction failed: {exc}") from exc
        return GatewayExtractResponse.model_validate(payload)

    async def crawl(
        self,
        *,
        url: str,
        max_pages: int,
        max_depth: int,
        max_bytes: int,
    ) -> GatewayCrawlResponse:
        try:
            payload = await call_gateway_proxy(
                "internet/crawl",
                {
                    "url": url,
                    "max_pages": max_pages,
                    "max_depth": max_depth,
                    "max_bytes": max_bytes,
                },
                timeout_s=60,
            )
        except GatewayEgressError as exc:
            raise InternetScoutGatewayError(f"Beacon crawl failed: {exc}") from exc
        return GatewayCrawlResponse.model_validate(payload)
