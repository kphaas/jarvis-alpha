from __future__ import annotations

from datetime import UTC, datetime

import pytest

from brain.services.internet_scout.executor import InternetScoutExecutor
from brain.services.internet_scout.gateway_client import InternetScoutGatewayClient
from brain.services.internet_scout.models import (
    GatewayExtractResponse,
    InternetScoutRequest,
    InternetTool,
)


class FakeGatewayClient(InternetScoutGatewayClient):
    def __init__(self) -> None:
        self.extract_calls: list[dict[str, object]] = []

    async def search(self, *, query: str, count: int = 5):
        raise AssertionError("search should not be called for extract requests")

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
