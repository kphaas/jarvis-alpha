"""Daily global market snapshot generation for Helm.

This is read-only market data for operator awareness. It never touches broker
accounts, positions, orders, or execution paths.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal, Protocol
from urllib.parse import quote

from pydantic import BaseModel, Field

from brain.registry.data_sources import DataSourceEntry, load_data_source_registry
from brain.services.internet_scout.gateway_client import InternetScoutGatewayClient
from brain.services.internet_scout.models import (
    GatewayFetchResponse,
    InternetScoutRequest,
    InternetTool,
)
from brain.services.internet_scout.orchestrator import InternetScoutOrchestrator
from brain.services.internet_scout.repository import InternetScoutRepository
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

MARKET_BRIEF_EVENT_TYPE = "market_global_brief"
MARKET_BRIEF_REQUESTER = "alpha_auto.market_global_brief"
MARKET_BRIEF_QUERY = "Daily global market snapshot for Helm"
MARKET_BRIEF_SCHEMA_VERSION: Literal["market_global_brief.v1"] = (
    "market_global_brief.v1"
)
MARKET_DATA_SOURCE_ID = "yahoo-finance-chart"
MARKET_MAX_BYTES = 300_000


@dataclass(frozen=True)
class MarketEndpoint:
    source_id: str
    symbol: str
    name: str
    region: str
    url: str
    source_name: str = "Market data"
    source_url: str = ""


class MarketGateway(Protocol):
    async def fetch(self, *, url: str, max_bytes: int) -> GatewayFetchResponse: ...


class MarketIndexQuote(BaseModel):
    source_id: str
    symbol: str
    name: str
    region: str
    currency: str = "unknown"
    price: float
    previous_close: float | None = None
    change: float | None = None
    change_percent: float | None = None
    as_of: datetime
    exchange_timezone: str | None = None
    source_name: str = "Yahoo Finance Chart"
    source_url: str
    raw_web_content_is_untrusted: bool = True


class MarketBriefSourceStatus(BaseModel):
    source_id: str
    source_name: str
    region: str
    symbol: str
    url: str
    status: Literal["ok", "degraded"]
    item_count: int = 0
    fetched_at: datetime | None = None
    content_hash: str | None = None
    detail: str | None = None


class MarketBriefControls(BaseModel):
    generated_by: Literal["alpha_auto"] = "alpha_auto"
    egress_owner: Literal["gateway"] = "gateway"
    summary_mode: Literal["deterministic"] = "deterministic"
    raw_web_content_is_untrusted: bool = True
    mutation_mode: Literal["read_only"] = "read_only"
    execution_mode: Literal["no_orders"] = "no_orders"


class MarketBrief(BaseModel):
    schema_version: Literal["market_global_brief.v1"] = MARKET_BRIEF_SCHEMA_VERSION
    status: Literal["ok", "degraded", "missing"] = "missing"
    generated_at: datetime
    age_hours: int = 0
    overall_summary: str = ""
    index_count: int = 0
    up_count: int = 0
    down_count: int = 0
    flat_count: int = 0
    source_count: int = 0
    failed_source_count: int = 0
    quotes: list[MarketIndexQuote] = Field(default_factory=list)
    source_statuses: list[MarketBriefSourceStatus] = Field(default_factory=list)
    controls: MarketBriefControls = Field(default_factory=MarketBriefControls)


GLOBAL_MARKET_INDEXES: tuple[tuple[str, str, str, str], ...] = (
    ("sp500", "^GSPC", "S&P 500", "United States"),
    ("nasdaq", "^IXIC", "Nasdaq Composite", "United States"),
    ("dow", "^DJI", "Dow Jones Industrial Average", "United States"),
    ("ftse100", "^FTSE", "FTSE 100", "United Kingdom"),
    ("dax", "^GDAXI", "DAX", "Germany"),
    ("cac40", "^FCHI", "CAC 40", "France"),
    ("nikkei225", "^N225", "Nikkei 225", "Japan"),
    ("hangseng", "^HSI", "Hang Seng Index", "Hong Kong"),
    ("shanghai", "000001.SS", "Shanghai Composite", "China"),
    ("asx200", "^AXJO", "S&P/ASX 200", "Australia"),
    ("bovespa", "^BVSP", "Bovespa", "Brazil"),
    ("tsx", "^GSPTSE", "S&P/TSX Composite", "Canada"),
    ("nifty50", "^NSEI", "Nifty 50", "India"),
)


def market_endpoints(
    registry: Mapping[str, DataSourceEntry] | None = None,
) -> list[MarketEndpoint]:
    registry = registry or load_data_source_registry()
    entry = registry[MARKET_DATA_SOURCE_ID]
    if not entry.api_base_url:
        raise ValueError(f"{MARKET_DATA_SOURCE_ID} missing api_base_url")
    chart_base_url = entry.api_base_url.rstrip("/")
    quote_base_url = f"{entry.url.rstrip('/')}/quote"
    return [
        MarketEndpoint(
            source_id=f"{entry.id}:{source_id}",
            symbol=symbol,
            name=name,
            region=region,
            url=f"{chart_base_url}/{quote(symbol, safe='')}?range=5d&interval=1d",
            source_name=entry.name,
            source_url=f"{quote_base_url}/{quote(symbol, safe='')}",
        )
        for source_id, symbol, name, region in GLOBAL_MARKET_INDEXES
    ]


async def build_market_brief(
    *,
    gateway: MarketGateway | None = None,
    generated_at: datetime | None = None,
) -> MarketBrief:
    """Fetch global market indexes through Gateway and build a snapshot."""

    generated_at = _utc(generated_at or datetime.now(UTC))
    gateway = gateway or InternetScoutGatewayClient()
    quotes: list[MarketIndexQuote] = []
    statuses: list[MarketBriefSourceStatus] = []

    for endpoint in market_endpoints():
        try:
            fetched = await gateway.fetch(url=endpoint.url, max_bytes=MARKET_MAX_BYTES)
            quote_item = parse_yahoo_chart_quote(
                fetched.text,
                endpoint=endpoint,
                fetched_at=fetched.fetched_at,
            )
            quotes.append(quote_item)
            statuses.append(
                MarketBriefSourceStatus(
                    source_id=endpoint.source_id,
                    source_name=endpoint.name,
                    region=endpoint.region,
                    symbol=endpoint.symbol,
                    url=fetched.url,
                    status="ok",
                    item_count=1,
                    fetched_at=_utc(fetched.fetched_at),
                    content_hash=fetched.content_hash,
                )
            )
        except Exception as exc:
            logger.warning(
                "MARKET_BRIEF_SOURCE_FAILED",
                extra={
                    "event": "MARKET_BRIEF_SOURCE_FAILED",
                    "source_id": endpoint.source_id,
                    "symbol": endpoint.symbol,
                    "region": endpoint.region,
                    "error_type": type(exc).__name__,
                },
            )
            statuses.append(
                MarketBriefSourceStatus(
                    source_id=endpoint.source_id,
                    source_name=endpoint.name,
                    region=endpoint.region,
                    symbol=endpoint.symbol,
                    url=endpoint.url,
                    status="degraded",
                    detail="source_fetch_or_parse_failed",
                )
            )

    failed = sum(1 for status in statuses if status.status == "degraded")
    up, down, flat = _market_direction_counts(quotes)
    if not statuses:
        status: Literal["ok", "degraded", "missing"] = "missing"
    elif failed:
        status = "degraded"
    else:
        status = "ok"

    brief = MarketBrief(
        status=status,
        generated_at=generated_at,
        overall_summary=_overall_summary(quotes, failed),
        index_count=len(quotes),
        up_count=up,
        down_count=down,
        flat_count=flat,
        source_count=len(statuses),
        failed_source_count=failed,
        quotes=quotes,
        source_statuses=statuses,
    )
    logger.info(
        "MARKET_BRIEF_BUILT",
        extra={
            "event": "MARKET_BRIEF_BUILT",
            "status": brief.status,
            "index_count": brief.index_count,
            "failed_source_count": brief.failed_source_count,
        },
    )
    return brief


async def run_market_brief_once(
    conn,
    *,
    gateway: MarketGateway | None = None,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """Generate and persist the daily market snapshot as a Beacon audit event."""

    brief = await build_market_brief(gateway=gateway, generated_at=generated_at)
    request = InternetScoutRequest(
        query=MARKET_BRIEF_QUERY,
        tool_hint=InternetTool.FETCH,
        max_pages=1,
        requester=MARKET_BRIEF_REQUESTER,
    )
    plan = InternetScoutOrchestrator().plan(request)
    repo = InternetScoutRepository(conn)
    request_id = await repo.create_request(
        user_id="system",
        request=request,
        decision=plan.decision,
        status_override="succeeded" if brief.status != "missing" else "failed",
    )
    metadata = brief.model_dump(mode="json")
    metadata["request_id"] = str(request_id)
    await repo.record_tool_event(
        request_id=request_id,
        tool=plan.decision.tool.value,
        event_type=MARKET_BRIEF_EVENT_TYPE,
        status="succeeded" if brief.status != "missing" else "failed",
        metadata=metadata,
    )
    return metadata


async def latest_market_brief(
    conn,
    *,
    generated_at: datetime | None = None,
) -> MarketBrief:
    """Return the latest persisted market snapshot for Helm without egress."""

    checked_at = _utc(generated_at or datetime.now(UTC))
    row = await conn.fetchrow(
        """
        SELECT request_id, status, metadata, created_at
        FROM public.alpha_internet_tool_events
        WHERE event_type = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        MARKET_BRIEF_EVENT_TYPE,
    )
    if not row:
        return MarketBrief(
            status="missing",
            generated_at=checked_at,
            overall_summary="No global market brief has been generated yet.",
        )

    metadata = _row_value(row, "metadata", {})
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    if not isinstance(metadata, Mapping):
        metadata = {}
    brief = MarketBrief.model_validate(metadata)
    brief.age_hours = max(
        0,
        int((checked_at - _utc(brief.generated_at)).total_seconds() // 3600),
    )
    return brief


def parse_yahoo_chart_quote(
    text: str,
    *,
    endpoint: MarketEndpoint,
    fetched_at: datetime,
) -> MarketIndexQuote:
    data = json.loads(text)
    chart = data.get("chart")
    if not isinstance(chart, Mapping):
        raise ValueError("missing_chart")
    if chart.get("error"):
        raise ValueError("chart_error")
    results = chart.get("result")
    if not isinstance(results, Sequence) or not results:
        raise ValueError("missing_chart_result")
    result = results[0]
    if not isinstance(result, Mapping):
        raise ValueError("invalid_chart_result")
    raw_meta = result.get("meta")
    meta: Mapping[str, object] = raw_meta if isinstance(raw_meta, Mapping) else {}
    quotes = _quote_closes(result)
    price = _number(meta.get("regularMarketPrice"))
    if price is None:
        price = _last_number(quotes)
    if price is None:
        raise ValueError("missing_price")
    previous_close = _previous_close(quotes, price) or _number(
        meta.get("chartPreviousClose")
    )
    change = None
    change_percent = None
    if previous_close and previous_close > 0:
        change = round(price - previous_close, 4)
        change_percent = round((change / previous_close) * 100, 2)

    raw_timestamps = result.get("timestamp")
    timestamps = (
        list(raw_timestamps)
        if isinstance(raw_timestamps, Sequence)
        and not isinstance(raw_timestamps, (str, bytes))
        else []
    )
    market_time = _number(meta.get("regularMarketTime")) or _last_number(timestamps)
    as_of = (
        datetime.fromtimestamp(int(market_time), tz=UTC)
        if market_time is not None
        else _utc(fetched_at)
    )
    return MarketIndexQuote(
        source_id=endpoint.source_id,
        symbol=endpoint.symbol,
        name=_clean_text(str(meta.get("shortName") or endpoint.name)),
        region=endpoint.region,
        currency=_clean_text(str(meta.get("currency") or "unknown")),
        price=round(price, 4),
        previous_close=round(previous_close, 4) if previous_close is not None else None,
        change=change,
        change_percent=change_percent,
        as_of=as_of,
        exchange_timezone=_clean_text(str(meta.get("exchangeTimezoneName") or ""))
        or None,
        source_name=endpoint.source_name,
        source_url=endpoint.source_url or endpoint.url,
    )


def _quote_closes(result: Mapping[str, object]) -> list[object]:
    indicators = result.get("indicators")
    if not isinstance(indicators, Mapping):
        return []
    quote_items = indicators.get("quote")
    if not isinstance(quote_items, Sequence) or not quote_items:
        return []
    first = quote_items[0]
    if not isinstance(first, Mapping):
        return []
    closes = first.get("close")
    return list(closes) if isinstance(closes, Sequence) else []


def _market_direction_counts(
    quotes: Sequence[MarketIndexQuote],
) -> tuple[int, int, int]:
    up = down = flat = 0
    for quote_item in quotes:
        pct = quote_item.change_percent
        if pct is None or abs(pct) < 0.05:
            flat += 1
        elif pct > 0:
            up += 1
        else:
            down += 1
    return up, down, flat


def _overall_summary(quotes: Sequence[MarketIndexQuote], failed: int) -> str:
    if not quotes:
        return f"No global market indexes were extracted; {failed} source(s) degraded."
    up, down, flat = _market_direction_counts(quotes)
    leaders = _format_movers(
        sorted(
            [quote for quote in quotes if quote.change_percent is not None],
            key=lambda quote: quote.change_percent or 0,
            reverse=True,
        )[:2]
    )
    laggards = _format_movers(
        sorted(
            [quote for quote in quotes if quote.change_percent is not None],
            key=lambda quote: quote.change_percent or 0,
        )[:2]
    )
    degraded = f" {failed} source(s) degraded." if failed else ""
    return (
        f"Global market snapshot: {up} up, {down} down, {flat} flat across "
        f"{len(quotes)} indexes. Leaders: {leaders}. Laggards: {laggards}."
        f"{degraded}"
    )


def _format_movers(quotes: Sequence[MarketIndexQuote]) -> str:
    if not quotes:
        return "none"
    return ", ".join(
        f"{quote.name} {quote.change_percent:+.2f}%"
        for quote in quotes
        if quote.change_percent is not None
    )


def _previous_close(values: Sequence[object], current_price: float) -> float | None:
    closes = [_number(value) for value in values]
    closes = [value for value in closes if value is not None]
    if len(closes) >= 2:
        return closes[-2]
    if len(closes) == 1 and closes[0] != current_price:
        return closes[0]
    return None


def _last_number(values: Sequence[object]) -> float | None:
    for value in reversed(values):
        number = _number(value)
        if number is not None:
            return number
    return None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:200]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _hash_parts(*parts: object) -> str:
    payload = "\n".join(str(part) for part in parts if part is not None)
    return sha256(payload.encode("utf-8")).hexdigest()


def _row_value(row: object, key: str, default: object | None = None) -> object | None:
    if isinstance(row, Mapping):
        return row.get(key, default)
    try:
        return row[key]  # type: ignore[index]
    except (KeyError, TypeError):
        return default
