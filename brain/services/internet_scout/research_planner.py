"""Deterministic research planning for Beacon search requests."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from brain.services.internet_scout.models import (
    InternetScoutResearchPlan,
    InternetScoutResearchQuery,
    InternetScoutRequest,
    InternetTool,
    ResearchIntent,
)

_OFFICIAL_MARKERS = (
    "official",
    "api reference",
    "api docs",
    "documentation",
    "docs",
    "sdk",
    "release notes",
    "changelog",
    "status page",
    "terms of service",
    "privacy policy",
)
_FRESHNESS_MARKERS = (
    "current",
    "today",
    "latest",
    "recent",
    "now",
    "newest",
    "release",
    "version",
    "price",
    "pricing",
)
_COMPARISON_MARKERS = ("compare", "comparison", " vs ", " versus ", "better than")
_TROUBLESHOOTING_MARKERS = (
    "error",
    "exception",
    "traceback",
    "failing",
    "failed",
    "fix",
    "bug",
    "troubleshoot",
)
_PRIMARY_SOURCE_MARKERS = (
    "legal",
    "medical",
    "financial",
    "tax",
    "law",
    "regulation",
    "standard",
    "security advisory",
)


def plan_research(
    request: InternetScoutRequest,
    *,
    selected_tool: InternetTool,
) -> InternetScoutResearchPlan:
    """Build a bounded search strategy before Gateway-owned egress."""
    search_text = _collapse_whitespace(request.query or "")
    query = _normalize(search_text)
    max_searches = _max_searches(request=request, selected_tool=selected_tool)
    intent = _intent_for_query(query)
    authority_required = _authority_required(query=query, intent=intent)
    freshness_required = any(marker in query for marker in _FRESHNESS_MARKERS)
    primary_source_required = authority_required or any(
        marker in query for marker in _PRIMARY_SOURCE_MARKERS
    )

    searches = _queries_for_intent(
        query=search_text,
        normalized_query=query,
        intent=intent,
        max_searches=max_searches,
        authority_required=authority_required,
        freshness_required=freshness_required,
    )
    notes = [
        f"research_intent:{intent}",
        f"search_budget:{len(searches)}",
    ]
    if authority_required:
        notes.append("authority_required")
    if freshness_required:
        notes.append("freshness_required")
    if primary_source_required:
        notes.append("primary_source_required")

    return InternetScoutResearchPlan(
        intent=intent,
        searches=searches,
        authority_required=authority_required,
        freshness_required=freshness_required,
        primary_source_required=primary_source_required,
        max_searches=max_searches,
        notes=notes,
    )


def _max_searches(
    *,
    request: InternetScoutRequest,
    selected_tool: InternetTool,
) -> int:
    if selected_tool != InternetTool.SEARCH or not request.query:
        return 1
    if request.requester.endswith(".deep_research"):
        return min(max(request.max_pages, 3), 6)
    return 1


def _queries_for_intent(
    *,
    query: str,
    normalized_query: str,
    intent: ResearchIntent,
    max_searches: int,
    authority_required: bool,
    freshness_required: bool,
) -> list[InternetScoutResearchQuery]:
    if not query:
        return []

    planned: list[InternetScoutResearchQuery] = [
        InternetScoutResearchQuery(
            query=_bounded_query(query),
            purpose="baseline",
            required=True,
        )
    ]

    if authority_required:
        planned.append(
            InternetScoutResearchQuery(
                query=_bounded_query(f"{query} official documentation"),
                purpose="official_source",
                required=True,
            )
        )
        official_site_query = _official_site_query(
            query=query,
            normalized_query=normalized_query,
        )
        if official_site_query:
            planned.append(
                InternetScoutResearchQuery(
                    query=_bounded_query(official_site_query),
                    purpose="official_source",
                    required=True,
                )
            )

    if freshness_required:
        planned.append(
            InternetScoutResearchQuery(
                query=_bounded_query(f"{query} latest official"),
                purpose="recency",
            )
        )

    if intent == "comparison":
        planned.append(
            InternetScoutResearchQuery(
                query=_bounded_query(f"{query} official comparison documentation"),
                purpose="comparison",
            )
        )
    elif intent == "troubleshooting":
        planned.append(
            InternetScoutResearchQuery(
                query=_bounded_query(f"{query} official troubleshooting documentation"),
                purpose="primary_source",
            )
        )
    elif not authority_required and max_searches > 1:
        planned.append(
            InternetScoutResearchQuery(
                query=_bounded_query(f"{query} primary source"),
                purpose="primary_source",
            )
        )

    planned.append(
        InternetScoutResearchQuery(
            query=_bounded_query(f"{query} source"),
            purpose="cross_check",
        )
    )
    return _dedupe_queries(planned)[:max_searches]


def _official_site_query(*, query: str, normalized_query: str) -> str | None:
    hosts = _hosts_from_query(normalized_query)
    if "openai" in normalized_query:
        hosts.extend(["platform.openai.com", "docs.openai.com"])
    if "github" in normalized_query:
        hosts.extend(["docs.github.com"])
    if "anthropic" in normalized_query:
        hosts.extend(["docs.anthropic.com"])
    if "stripe" in normalized_query:
        hosts.extend(["docs.stripe.com"])
    if not hosts:
        return None
    site_filter = " OR ".join(f"site:{host}" for host in _dedupe_strings(hosts)[:3])
    return f"{query} ({site_filter})"


def _intent_for_query(query: str) -> ResearchIntent:
    if any(marker in query for marker in _OFFICIAL_MARKERS):
        return "official_docs"
    if any(marker in query for marker in _COMPARISON_MARKERS):
        return "comparison"
    if any(marker in query for marker in _TROUBLESHOOTING_MARKERS):
        return "troubleshooting"
    if any(marker in query for marker in _FRESHNESS_MARKERS):
        return "current_fact"
    return "general"


def _authority_required(*, query: str, intent: ResearchIntent) -> bool:
    return intent in {"official_docs", "current_fact"} or any(
        marker in query for marker in _PRIMARY_SOURCE_MARKERS
    )


def _hosts_from_query(query: str) -> list[str]:
    hosts: list[str] = []
    for token in re.findall(r"\b[a-z0-9.-]+\.[a-z]{2,}\b", query):
        parsed = urlparse(token if "://" in token else f"https://{token}")
        if parsed.hostname:
            hosts.append(parsed.hostname.strip(".").lower())
    return hosts


def _dedupe_queries(
    queries: list[InternetScoutResearchQuery],
) -> list[InternetScoutResearchQuery]:
    seen: set[str] = set()
    deduped: list[InternetScoutResearchQuery] = []
    for item in queries:
        key = item.query.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip(".").lower() for value in values if value))


def _normalize(value: str) -> str:
    return _collapse_whitespace(value).lower()


def _bounded_query(value: str) -> str:
    return value[:500].strip()


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
