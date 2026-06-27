"""Daily AI vendor brief generation for Helm.

The brief treats fetched vendor content as untrusted evidence. Brain only calls
Gateway-owned egress endpoints, then persists a redacted summary event for Helm.
"""

from __future__ import annotations

import html
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
from typing import Literal, Protocol
from urllib.parse import urljoin
from xml.etree import ElementTree

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
from brain.services.internet_scout.safety import DEFAULT_MAX_CONTENT_BYTES
from brain.services.internet_scout.sanitizer import sanitize_untrusted_text
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

AI_NEWS_BRIEF_EVENT_TYPE = "ai_news_daily_brief"
AI_NEWS_BRIEF_REQUESTER = "alpha_auto.ai_news_daily_brief"
AI_NEWS_BRIEF_QUERY = "Daily AI vendor news summary for Helm"
AI_NEWS_BRIEF_SCHEMA_VERSION: Literal["ai_news_daily_brief.v1"] = (
    "ai_news_daily_brief.v1"
)
DEFAULT_AI_NEWS_WINDOW_HOURS = 24
DEFAULT_AI_NEWS_MAX_ITEMS = 12
RSS_MAX_BYTES = DEFAULT_MAX_CONTENT_BYTES
PAGE_MAX_BYTES = 500_000

_RSS_SOURCE_IDS = (
    "openai-news-rss",
    "aws-whats-new-ai",
    "azure-ai-blog",
    "github-copilot-changelog",
)
_PAGE_SOURCE_IDS = (
    "openai-api-changelog",
    "anthropic-api-release-notes",
    "google-gemini-api-changelog",
)


@dataclass(frozen=True)
class AiNewsEndpoint:
    source_id: str
    name: str
    vendor: str
    url: str
    kind: Literal["rss", "page"]


class AiNewsGateway(Protocol):
    async def fetch(self, *, url: str, max_bytes: int) -> GatewayFetchResponse: ...


class AiNewsBriefItem(BaseModel):
    title: str
    vendor: str
    source_id: str
    source_name: str
    url: str
    published_at: datetime | None = None
    summary: str = ""
    content_hash: str
    risk_markers: list[str] = Field(default_factory=list)
    raw_web_content_is_untrusted: bool = True


class AiNewsBriefSourceStatus(BaseModel):
    source_id: str
    source_name: str
    vendor: str
    url: str
    status: Literal["ok", "degraded", "skipped"]
    kind: Literal["rss", "page"]
    item_count: int = 0
    recent_item_count: int = 0
    fetched_at: datetime | None = None
    content_hash: str | None = None
    risk_marker_count: int = 0
    detail: str | None = None


class AiNewsBriefControls(BaseModel):
    generated_by: Literal["alpha_auto"] = "alpha_auto"
    egress_owner: Literal["gateway"] = "gateway"
    summary_mode: Literal["deterministic"] = "deterministic"
    llm_summary_used: bool = False
    raw_web_content_is_untrusted: bool = True
    mutation_mode: Literal["read_only"] = "read_only"


class AiNewsBrief(BaseModel):
    schema_version: Literal["ai_news_daily_brief.v1"] = AI_NEWS_BRIEF_SCHEMA_VERSION
    status: Literal["ok", "degraded", "missing"] = "missing"
    generated_at: datetime
    window_hours: int = DEFAULT_AI_NEWS_WINDOW_HOURS
    age_hours: int = 0
    overall_summary: str = ""
    item_count: int = 0
    recent_item_count: int = 0
    source_count: int = 0
    failed_source_count: int = 0
    top_items: list[AiNewsBriefItem] = Field(default_factory=list)
    source_statuses: list[AiNewsBriefSourceStatus] = Field(default_factory=list)
    controls: AiNewsBriefControls = Field(default_factory=AiNewsBriefControls)


def ai_news_endpoints(
    registry: Mapping[str, DataSourceEntry] | None = None,
) -> list[AiNewsEndpoint]:
    """Build official AI vendor endpoints from the vendored registry."""

    registry = registry or load_data_source_registry()
    endpoints: list[AiNewsEndpoint] = []
    for source_id in _RSS_SOURCE_IDS:
        entry = registry[source_id]
        if not entry.api_base_url:
            continue
        endpoints.append(
            AiNewsEndpoint(
                source_id=source_id,
                name=entry.name,
                vendor=_vendor_for_source(source_id),
                url=entry.api_base_url,
                kind="rss",
            )
        )

    for source_id in _PAGE_SOURCE_IDS:
        entry = registry[source_id]
        endpoints.append(
            AiNewsEndpoint(
                source_id=source_id,
                name=entry.name,
                vendor=_vendor_for_source(source_id),
                url=entry.api_base_url or entry.url,
                kind="page",
            )
        )

    status_entry = registry["ai-vendor-status-feeds"]
    for status_url in _status_feed_urls(status_entry):
        endpoints.append(
            AiNewsEndpoint(
                source_id=status_entry.id,
                name=f"{_vendor_for_url(status_url)} Status RSS",
                vendor=_vendor_for_url(status_url),
                url=status_url,
                kind="rss",
            )
        )
    return endpoints


async def build_ai_news_brief(
    *,
    gateway: AiNewsGateway | None = None,
    registry: Mapping[str, DataSourceEntry] | None = None,
    generated_at: datetime | None = None,
    window_hours: int = DEFAULT_AI_NEWS_WINDOW_HOURS,
    max_items: int = DEFAULT_AI_NEWS_MAX_ITEMS,
) -> AiNewsBrief:
    """Fetch official vendor sources and build a deterministic brief."""

    generated_at = _utc(generated_at or datetime.now(UTC))
    gateway = gateway or InternetScoutGatewayClient()
    cutoff = generated_at - timedelta(hours=window_hours)
    items: list[AiNewsBriefItem] = []
    statuses: list[AiNewsBriefSourceStatus] = []

    for endpoint in ai_news_endpoints(registry):
        try:
            max_bytes = RSS_MAX_BYTES if endpoint.kind == "rss" else PAGE_MAX_BYTES
            fetched = await gateway.fetch(url=endpoint.url, max_bytes=max_bytes)
            if endpoint.kind == "rss":
                parsed_items = parse_feed_items(
                    fetched.text,
                    endpoint=endpoint,
                    content_hash=fetched.content_hash,
                )
            else:
                parsed_items = parse_page_monitor_items(
                    fetched.text,
                    endpoint=endpoint,
                    content_hash=fetched.content_hash,
                )
            recent = [
                item
                for item in parsed_items
                if item.published_at is None or item.published_at >= cutoff
            ]
            items.extend(recent)
            risk_marker_count = sum(len(item.risk_markers) for item in parsed_items)
            statuses.append(
                AiNewsBriefSourceStatus(
                    source_id=endpoint.source_id,
                    source_name=endpoint.name,
                    vendor=endpoint.vendor,
                    url=fetched.url,
                    status="ok",
                    kind=endpoint.kind,
                    item_count=len(parsed_items),
                    recent_item_count=len(recent),
                    fetched_at=_utc(fetched.fetched_at),
                    content_hash=fetched.content_hash,
                    risk_marker_count=risk_marker_count,
                    detail=None
                    if parsed_items
                    else "source_fetched_but_no_items_extracted",
                )
            )
        except Exception as exc:
            logger.warning(
                "AI_NEWS_BRIEF_SOURCE_FAILED",
                extra={
                    "event": "AI_NEWS_BRIEF_SOURCE_FAILED",
                    "source_id": endpoint.source_id,
                    "vendor": endpoint.vendor,
                    "kind": endpoint.kind,
                    "error_type": type(exc).__name__,
                },
            )
            statuses.append(
                AiNewsBriefSourceStatus(
                    source_id=endpoint.source_id,
                    source_name=endpoint.name,
                    vendor=endpoint.vendor,
                    url=endpoint.url,
                    status="degraded",
                    kind=endpoint.kind,
                    detail="source_fetch_or_parse_failed",
                )
            )

    ranked = sorted(
        items,
        key=lambda item: (
            item.published_at or generated_at,
            _vendor_priority(item.vendor),
            item.title,
        ),
        reverse=True,
    )[:max_items]
    failed = sum(1 for status in statuses if status.status == "degraded")
    status: Literal["ok", "degraded", "missing"]
    if not statuses:
        status = "missing"
    elif failed:
        status = "degraded"
    else:
        status = "ok"

    brief = AiNewsBrief(
        status=status,
        generated_at=generated_at,
        window_hours=window_hours,
        overall_summary=_overall_summary(ranked, statuses, window_hours),
        item_count=len(items),
        recent_item_count=len(ranked),
        source_count=len(statuses),
        failed_source_count=failed,
        top_items=ranked,
        source_statuses=statuses,
    )
    logger.info(
        "AI_NEWS_BRIEF_BUILT",
        extra={
            "event": "AI_NEWS_BRIEF_BUILT",
            "status": brief.status,
            "source_count": brief.source_count,
            "failed_source_count": brief.failed_source_count,
            "item_count": brief.item_count,
        },
    )
    return brief


async def run_ai_news_brief_once(
    conn,
    *,
    gateway: AiNewsGateway | None = None,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    """Generate and persist the daily brief as a Beacon audit event."""

    brief = await build_ai_news_brief(gateway=gateway, generated_at=generated_at)
    request = InternetScoutRequest(
        query=AI_NEWS_BRIEF_QUERY,
        tool_hint=InternetTool.FETCH,
        max_pages=1,
        requester=AI_NEWS_BRIEF_REQUESTER,
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
        event_type=AI_NEWS_BRIEF_EVENT_TYPE,
        status="succeeded" if brief.status != "missing" else "failed",
        metadata=metadata,
    )
    return metadata


async def latest_ai_news_brief(
    conn,
    *,
    generated_at: datetime | None = None,
) -> AiNewsBrief:
    """Return the latest persisted brief for Helm without doing egress."""

    checked_at = _utc(generated_at or datetime.now(UTC))
    row = await conn.fetchrow(
        """
        SELECT request_id, status, metadata, created_at
        FROM public.alpha_internet_tool_events
        WHERE event_type = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        AI_NEWS_BRIEF_EVENT_TYPE,
    )
    if not row:
        return AiNewsBrief(
            status="missing",
            generated_at=checked_at,
            overall_summary="No AI news brief has been generated yet.",
        )

    metadata = _row_value(row, "metadata", {})
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    if not isinstance(metadata, Mapping):
        metadata = {}
    brief = AiNewsBrief.model_validate(metadata)
    brief.age_hours = max(
        0,
        int((checked_at - _utc(brief.generated_at)).total_seconds() // 3600),
    )
    return brief


def parse_feed_items(
    text: str,
    *,
    endpoint: AiNewsEndpoint,
    content_hash: str,
) -> list[AiNewsBriefItem]:
    """Parse RSS or Atom text into redacted brief items."""

    root = ElementTree.fromstring(text)
    raw_items = list(root.findall(".//item"))
    if not raw_items:
        raw_items = [
            entry for entry in root.iter() if _local_name(entry.tag).lower() == "entry"
        ]

    items: list[AiNewsBriefItem] = []
    for raw in raw_items[:25]:
        title = _clean_text(_child_text(raw, "title")) or "Untitled update"
        url = _clean_text(_child_text(raw, "link")) or _atom_link(raw) or endpoint.url
        published = _parse_datetime(
            _child_text(raw, "pubDate")
            or _child_text(raw, "published")
            or _child_text(raw, "updated")
        )
        summary_text = _clean_text(
            _child_text(raw, "description")
            or _child_text(raw, "summary")
            or _child_text(raw, "content")
        )
        sanitized = sanitize_untrusted_text(summary_text, max_chars=500)
        item_hash = _hash_parts(endpoint.source_id, title, url, str(published))
        items.append(
            AiNewsBriefItem(
                title=title[:300],
                vendor=endpoint.vendor,
                source_id=endpoint.source_id,
                source_name=endpoint.name,
                url=url,
                published_at=published,
                summary=sanitized.text[:500],
                content_hash=item_hash or content_hash,
                risk_markers=sanitized.risk_markers,
            )
        )
    return _dedupe_items(items)


def parse_page_monitor_items(
    text: str,
    *,
    endpoint: AiNewsEndpoint,
    content_hash: str,
) -> list[AiNewsBriefItem]:
    """Extract stable monitor links from an official page source."""

    links = _page_links(text, endpoint.url)
    if endpoint.source_id != "openai-api-changelog":
        links = links[:5]
    sanitized = sanitize_untrusted_text(text, max_chars=2_000)
    title = f"{endpoint.name} monitor"
    return [
        AiNewsBriefItem(
            title=title,
            vendor=endpoint.vendor,
            source_id=endpoint.source_id,
            source_name=endpoint.name,
            url=endpoint.url,
            published_at=None,
            summary="Official page fetched for daily change monitoring.",
            content_hash=_hash_parts(content_hash, *links),
            risk_markers=sanitized.risk_markers,
        )
    ]


def _overall_summary(
    items: Sequence[AiNewsBriefItem],
    statuses: Sequence[AiNewsBriefSourceStatus],
    window_hours: int,
) -> str:
    failed = [status for status in statuses if status.status == "degraded"]
    if not items:
        if failed:
            return (
                f"No recent AI vendor items were extracted in the last "
                f"{window_hours}h; {len(failed)} source(s) degraded."
            )
        return (
            f"No recent official AI vendor items were extracted in the last "
            f"{window_hours}h."
        )

    vendors = Counter(item.vendor for item in items)
    leading = ", ".join(f"{vendor}: {count}" for vendor, count in vendors.most_common())
    degraded = f" {len(failed)} source(s) degraded." if failed else ""
    return (
        f"{len(items)} official AI vendor item(s) were found in the last "
        f"{window_hours}h across {len(vendors)} vendor(s): {leading}.{degraded}"
    )


def _vendor_for_source(source_id: str) -> str:
    if source_id.startswith("openai"):
        return "OpenAI"
    if source_id.startswith("aws"):
        return "AWS"
    if source_id.startswith("azure") or source_id == "github-copilot-changelog":
        return "Microsoft"
    if source_id.startswith("anthropic"):
        return "Anthropic"
    if source_id.startswith("google"):
        return "Google"
    if source_id.startswith("github"):
        return "GitHub"
    if source_id.startswith("huggingface"):
        return "Hugging Face"
    return "AI vendor"


def _vendor_for_url(url: str) -> str:
    if "openai" in url:
        return "OpenAI"
    if "claude" in url or "anthropic" in url:
        return "Anthropic"
    if "azure" in url or "microsoft" in url:
        return "Microsoft"
    if "aws" in url or "amazon" in url:
        return "AWS"
    return "AI vendor"


def _vendor_priority(vendor: str) -> int:
    return {
        "OpenAI": 6,
        "Anthropic": 5,
        "Google": 4,
        "Microsoft": 3,
        "AWS": 2,
    }.get(vendor, 1)


def _status_feed_urls(entry: DataSourceEntry) -> list[str]:
    raw_notes: list[str] = []
    auth = entry.raw.get("auth")
    if isinstance(auth, Mapping):
        raw_notes.append(str(auth.get("notes") or ""))
    raw_notes.append(str(entry.raw.get("notes") or ""))
    text = "\n".join(raw_notes)
    urls = re.findall(r"https://[^\s)]+", text)
    return [
        url.rstrip(".,")
        for url in dict.fromkeys(urls)
        if url.rstrip(".,").lower().endswith((".rss", "/feed/"))
    ]


def _child_text(element: ElementTree.Element, wanted: str) -> str:
    for child in element:
        if _local_name(child.tag).lower() == wanted.lower():
            return "".join(child.itertext()).strip()
    return ""


def _atom_link(element: ElementTree.Element) -> str | None:
    for child in element:
        if _local_name(child.tag).lower() != "link":
            continue
        href = child.attrib.get("href")
        if href:
            return href.strip()
    return None


def _local_name(tag: object) -> str:
    text = str(tag)
    return text.rsplit("}", 1)[-1] if "}" in text else text


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return _utc(parsed)


def _clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _page_links(text: str, base_url: str) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r'(?:"|href=)(/[^"\'<>\s]+)', text):
        url = urljoin(base_url, html.unescape(match.group(1)))
        if url in seen:
            continue
        seen.add(url)
        links.append(url)
    return links


def _dedupe_items(items: Sequence[AiNewsBriefItem]) -> list[AiNewsBriefItem]:
    seen: set[str] = set()
    unique: list[AiNewsBriefItem] = []
    for item in items:
        key = item.url or item.content_hash
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


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
