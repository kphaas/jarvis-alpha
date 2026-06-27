from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from brain.services.internet_scout.market_brief import (
    MarketEndpoint,
    build_market_brief,
    latest_market_brief,
    parse_yahoo_chart_quote,
    run_market_brief_once,
)
from brain.services.internet_scout.models import GatewayFetchResponse

NOW = datetime(2026, 6, 26, 12, 35, tzinfo=UTC)


def _chart_payload(
    *,
    symbol: str = "^GSPC",
    short_name: str = "S&P 500",
    currency: str = "USD",
    closes: list[float | None] | None = None,
    regular_price: float = 105.0,
    previous_close: float = 100.0,
) -> str:
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": symbol,
                            "shortName": short_name,
                            "currency": currency,
                            "regularMarketPrice": regular_price,
                            "chartPreviousClose": previous_close,
                            "regularMarketTime": int(NOW.timestamp()),
                            "exchangeTimezoneName": "America/New_York",
                        },
                        "timestamp": [
                            int((NOW - timedelta(days=1)).timestamp()),
                            int(NOW.timestamp()),
                        ],
                        "indicators": {
                            "quote": [
                                {
                                    "close": closes
                                    if closes is not None
                                    else [previous_close, regular_price]
                                }
                            ]
                        },
                    }
                ],
                "error": None,
            }
        }
    )


class FakeGateway:
    def __init__(self, payloads: dict[str, str]) -> None:
        self.payloads = payloads
        self.calls: list[dict[str, object]] = []

    async def fetch(self, *, url: str, max_bytes: int) -> GatewayFetchResponse:
        self.calls.append({"url": url, "max_bytes": max_bytes})
        if url not in self.payloads:
            raise RuntimeError("market source unavailable")
        return GatewayFetchResponse(
            url=url,
            host=url.split("/")[2],
            status_code=200,
            content_type="application/json",
            content_hash="c" * 64,
            fetched_at=NOW,
            text=self.payloads[url],
            truncated=False,
            risk_markers=[],
            redirect_chain=[url],
        )


class FakeConn:
    def __init__(self, latest_metadata: dict[str, object] | None = None) -> None:
        self.request_id = uuid4()
        self.latest_metadata = latest_metadata
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []
        self.execute_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, query: str, *args: object):
        self.fetchrow_calls.append((query, args))
        if "INSERT INTO public.alpha_internet_requests" in query:
            return {"id": self.request_id}
        if "FROM public.alpha_internet_tool_events" in query:
            if self.latest_metadata is None:
                return None
            return {
                "request_id": self.request_id,
                "status": "succeeded",
                "metadata": self.latest_metadata,
                "created_at": NOW,
            }
        raise AssertionError(f"unexpected query: {query}")

    async def execute(self, query: str, *args: object):
        self.execute_calls.append((query, args))
        if "INSERT INTO public.alpha_internet_tool_events" in query:
            return "INSERT 0 1"
        raise AssertionError(f"unexpected query: {query}")


def test_parse_yahoo_chart_quote_extracts_daily_change() -> None:
    endpoint = MarketEndpoint(
        source_id="yahoo-finance-chart:sp500",
        symbol="^GSPC",
        name="S&P 500",
        region="United States",
        url="https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC",
    )

    quote = parse_yahoo_chart_quote(
        _chart_payload(regular_price=105.0, previous_close=100.0),
        endpoint=endpoint,
        fetched_at=NOW,
    )

    assert quote.name == "S&P 500"
    assert quote.change == 5.0
    assert quote.change_percent == 5.0
    assert quote.raw_web_content_is_untrusted is True
    assert quote.source_url.endswith("%5EGSPC")


@pytest.mark.asyncio
async def test_build_market_brief_fetches_gateway_sources_and_degrades_per_source(
    monkeypatch,
) -> None:
    endpoints = [
        MarketEndpoint(
            source_id="yahoo-finance-chart:sp500",
            symbol="^GSPC",
            name="S&P 500",
            region="United States",
            url="https://market.test/sp500",
        ),
        MarketEndpoint(
            source_id="yahoo-finance-chart:ftse100",
            symbol="^FTSE",
            name="FTSE 100",
            region="United Kingdom",
            url="https://market.test/ftse",
        ),
    ]
    import brain.services.internet_scout.market_brief as market_brief_module

    monkeypatch.setattr(market_brief_module, "market_endpoints", lambda: endpoints)
    gateway = FakeGateway({"https://market.test/sp500": _chart_payload()})

    brief = await build_market_brief(gateway=gateway, generated_at=NOW)

    assert brief.status == "degraded"
    assert brief.index_count == 1
    assert brief.failed_source_count == 1
    assert brief.controls.execution_mode == "no_orders"
    assert "Global market snapshot" in brief.overall_summary
    assert all(call["max_bytes"] > 0 for call in gateway.calls)
    assert "market source unavailable" not in str(brief.model_dump())


@pytest.mark.asyncio
async def test_run_market_brief_once_persists_read_only_metadata(monkeypatch) -> None:
    endpoints = [
        MarketEndpoint(
            source_id="yahoo-finance-chart:sp500",
            symbol="^GSPC",
            name="S&P 500",
            region="United States",
            url="https://market.test/sp500",
        )
    ]
    import brain.services.internet_scout.market_brief as market_brief_module

    monkeypatch.setattr(market_brief_module, "market_endpoints", lambda: endpoints)
    conn = FakeConn()

    metadata = await run_market_brief_once(
        conn,
        gateway=FakeGateway({"https://market.test/sp500": _chart_payload()}),
        generated_at=NOW,
    )

    assert metadata["schema_version"] == "market_global_brief.v1"
    assert metadata["request_id"] == str(conn.request_id)
    assert metadata["controls"]["execution_mode"] == "no_orders"
    assert conn.fetchrow_calls[0][1][1] == "alpha_auto.market_global_brief"
    event_args = conn.execute_calls[0][1]
    assert event_args[2] == "market_global_brief"
    assert event_args[3] == "succeeded"
    assert "order" not in str(event_args).lower().replace("no_orders", "")


@pytest.mark.asyncio
async def test_latest_market_brief_returns_missing_without_egress() -> None:
    brief = await latest_market_brief(FakeConn(), generated_at=NOW)

    assert brief.status == "missing"
    assert brief.controls.egress_owner == "gateway"
    assert brief.controls.execution_mode == "no_orders"


@pytest.mark.asyncio
async def test_latest_market_brief_reports_age() -> None:
    metadata = {
        "schema_version": "market_global_brief.v1",
        "status": "ok",
        "generated_at": (NOW - timedelta(hours=2)).isoformat(),
        "overall_summary": "Global market snapshot.",
        "source_count": 1,
    }

    brief = await latest_market_brief(
        FakeConn(latest_metadata=metadata),
        generated_at=NOW,
    )

    assert brief.status == "ok"
    assert brief.age_hours == 2
