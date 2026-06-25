"""Registry-backed Beacon source selection.

This module is intentionally deterministic: it selects approved registry source
ids for a research plan, but it does not execute provider calls. Gateway remains
the egress owner for executable connectors and provider budgets.
"""

from __future__ import annotations

from collections.abc import Iterable

from brain.services.internet_scout.models import InternetScoutFocusMode

BEACON_EXECUTABLE_SEARCH_DATA_SOURCE_IDS: tuple[str, ...] = (
    "brave-search",
    "perplexity-search",
)

BEACON_EXECUTABLE_SOURCE_DATA_SOURCE_IDS: tuple[str, ...] = (
    "pubmed-eutils",
    "sec-edgar",
    "osv-dev",
    "cisa-kev",
)

BEACON_APPROVED_SOURCE_DATA_SOURCE_IDS: tuple[str, ...] = (
    "tavily-search",
    *BEACON_EXECUTABLE_SOURCE_DATA_SOURCE_IDS,
    "openalex",
    "google-workspace",
    "microsoft-graph",
)

BEACON_AI_VENDOR_WATCH_DATA_SOURCE_IDS: tuple[str, ...] = (
    "openai-news-rss",
    "openai-api-changelog",
    "aws-whats-new-ai",
    "azure-ai-blog",
    "github-copilot-changelog",
    "ai-vendor-status-feeds",
)

BEACON_ABILITY_DATA_SOURCE_IDS: tuple[str, ...] = (
    *BEACON_EXECUTABLE_SEARCH_DATA_SOURCE_IDS,
    *BEACON_APPROVED_SOURCE_DATA_SOURCE_IDS,
    *BEACON_AI_VENDOR_WATCH_DATA_SOURCE_IDS,
)

BEACON_ON_HOLD_DATA_SOURCE_IDS: tuple[str, ...] = ("quiverquant",)

_BASELINE_SOURCE_IDS = (
    "brave-search",
    "perplexity-search",
    "tavily-search",
)
_MEDICAL_MARKERS = (
    "biomedical",
    "clinical trial",
    "clinical",
    "drug",
    "medline",
    "medical",
    "nih",
    "patient",
    "pubmed",
    "therapy",
    "treatment",
)
_SEC_MARKERS = (
    "10-k",
    "10-q",
    "8-k",
    "annual report",
    "company facts",
    "edgar",
    "filing",
    "form 10",
    "sec",
    "xbrl",
)
_SEC_FALSE_POSITIVE_MARKERS = (
    "second",
    "section",
    "security",
    "secure",
)
_SEC_PRIMARY_MARKERS = ("filing", "edgar", "10-k", "10-q", "8-k", "xbrl")
_SEC_COMPANY_DISCLOSURE_MARKERS = ("annual report", "company facts", "sec")
_SEC_FINANCE_MARKERS = ("financial", "revenue", "earnings", "disclosure")
_SEC_COMPANY_TERMS = (
    "company",
    "corp",
    "corporation",
    "inc",
    "issuer",
    "public company",
)
_SEC_KNOWN_PUBLIC_COMPANIES = (
    "apple",
    "microsoft",
    "nvidia",
    "tesla",
    "amazon",
    "meta",
    "alphabet",
    "google",
)
_SECURITY_MARKERS = (
    "advisory",
    "cisa",
    "cve",
    "dependency",
    "exploit",
    "kev",
    "malware",
    "osv",
    "package vulnerability",
    "vulnerability",
)
_SCHOLARLY_MARKERS = (
    "academic",
    "citation",
    "doi",
    "journal",
    "literature review",
    "openalex",
    "paper",
    "peer reviewed",
    "publication",
    "research study",
    "scholarly",
)
_GOOGLE_WORKSPACE_MARKERS = (
    "calendar",
    "drive",
    "gmail",
    "google docs",
    "google workspace",
    "workspace",
)
_MICROSOFT_GRAPH_MARKERS = (
    "microsoft 365",
    "microsoft graph",
    "onedrive",
    "outlook",
    "sharepoint",
    "teams",
)
_AI_VENDOR_WATCH_MARKERS = (
    "ai news",
    "ai vendor",
    "ai vendors",
    "artificial intelligence news",
    "frontier model",
    "llm news",
    "model announcement",
    "model release",
)
_AI_STATUS_MARKERS = (
    "availability",
    "degraded",
    "downtime",
    "errors",
    "incident",
    "outage",
    "status",
)
_OPENAI_MARKERS = (
    "chatgpt",
    "gpt-",
    "open ai",
    "openai",
)
_AWS_AI_MARKERS = (
    "agentcore",
    "aws ai",
    "aws bedrock",
    "bedrock",
    "nova",
    "sagemaker",
)
_MICROSOFT_AI_MARKERS = (
    "azure ai",
    "copilot",
    "github copilot",
    "microsoft ai",
    "msft",
)
_ANTHROPIC_MARKERS = (
    "anthropic",
    "claude",
)


def select_beacon_data_source_ids(
    query: str | None,
    *,
    focus_mode: InternetScoutFocusMode,
    allowed_data_source_ids: Iterable[str] = BEACON_ABILITY_DATA_SOURCE_IDS,
) -> tuple[str, ...]:
    """Return approved registry source ids that fit the request.

    The returned ids are an ability/plan contract, not a promise that Gateway has
    an executable connector for every source today.
    """

    normalized = _normalize(query or "")
    selected = list(_BASELINE_SOURCE_IDS)

    if focus_mode == "academic" or _contains_any(normalized, _SCHOLARLY_MARKERS):
        selected.append("openalex")
    if _contains_any(normalized, _MEDICAL_MARKERS):
        selected.append("pubmed-eutils")
    if _is_sec_filings_query(normalized):
        selected.append("sec-edgar")
    if _contains_any(normalized, _SECURITY_MARKERS):
        selected.extend(["osv-dev", "cisa-kev"])
    if _contains_any(normalized, _GOOGLE_WORKSPACE_MARKERS):
        selected.append("google-workspace")
    if _contains_any(normalized, _MICROSOFT_GRAPH_MARKERS):
        selected.append("microsoft-graph")
    selected.extend(_select_ai_vendor_watch_sources(normalized))

    return _allowed_unique(selected, allowed_data_source_ids)


def assert_no_on_hold_data_sources(data_source_ids: Iterable[str]) -> None:
    """Fail closed if a paused paid source enters an executable allowlist."""

    blocked = sorted(set(data_source_ids).intersection(BEACON_ON_HOLD_DATA_SOURCE_IDS))
    if blocked:
        raise ValueError(
            "on-hold Beacon data sources are not allowed: " + ", ".join(blocked)
        )


def _allowed_unique(
    data_source_ids: Iterable[str],
    allowed_data_source_ids: Iterable[str],
) -> tuple[str, ...]:
    allowed = set(allowed_data_source_ids)
    selected = tuple(
        dict.fromkeys(
            data_source_id
            for data_source_id in data_source_ids
            if data_source_id in allowed
        )
    )
    assert_no_on_hold_data_sources(selected)
    return selected


def _contains_any(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value for marker in markers)


def _select_ai_vendor_watch_sources(query: str) -> tuple[str, ...]:
    if _contains_any(query, _AI_VENDOR_WATCH_MARKERS):
        return BEACON_AI_VENDOR_WATCH_DATA_SOURCE_IDS

    selected: list[str] = []
    matched_vendor = False
    if _contains_any(query, _OPENAI_MARKERS):
        selected.extend(["openai-news-rss", "openai-api-changelog"])
        matched_vendor = True
    if _contains_any(query, _AWS_AI_MARKERS):
        selected.append("aws-whats-new-ai")
        matched_vendor = True
    if _contains_any(query, _MICROSOFT_AI_MARKERS):
        selected.extend(["azure-ai-blog", "github-copilot-changelog"])
        matched_vendor = True
    if _contains_any(query, _ANTHROPIC_MARKERS):
        matched_vendor = True
    if matched_vendor and _contains_any(query, _AI_STATUS_MARKERS):
        selected.append("ai-vendor-status-feeds")
    return tuple(selected)


def _is_sec_filings_query(query: str) -> bool:
    if not _contains_any(query, _SEC_MARKERS):
        return False
    if _contains_any(query, _SEC_FALSE_POSITIVE_MARKERS) and not _contains_any(
        query,
        _SEC_PRIMARY_MARKERS,
    ):
        return False
    if _contains_any(query, _SEC_PRIMARY_MARKERS):
        return True
    if _contains_any(query, _SEC_COMPANY_DISCLOSURE_MARKERS):
        return _contains_any(query, _SEC_COMPANY_TERMS) or _contains_any(
            query,
            _SEC_FINANCE_MARKERS,
        )
    return False


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())
