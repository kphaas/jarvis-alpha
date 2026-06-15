"""Deterministic research planning for Beacon search requests."""

from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlparse

from brain.services.internet_scout.models import (
    InternetScoutResearchPlan,
    InternetScoutResearchQuery,
    InternetScoutResearchStopCriteria,
    InternetScoutResearchSubquestion,
    InternetScoutRequest,
    InternetTool,
    ResearchIntent,
    ResearchSourceType,
    SearchProvider,
    SearchProviderStrategy,
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
_COMPARISON_SPLIT_RE = re.compile(
    r"\s+(?:vs\.?|versus|and|against|to)\s+",
    flags=re.IGNORECASE,
)
_COMPARISON_SCOPE_RE = re.compile(
    r"\b(?:for|when|while|with|using)\b|[.?!]",
    flags=re.IGNORECASE,
)
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
    provider_strategy = _provider_strategy(
        request=request,
        selected_tool=selected_tool,
        max_searches=max_searches,
    )
    search_providers: list[SearchProvider] = (
        ["brave", "perplexity"] if provider_strategy == "fanout" else ["auto"]
    )
    max_extracts = _max_extracts(
        request=request,
        selected_tool=selected_tool,
        authority_required=authority_required,
        freshness_required=freshness_required,
        max_searches=max_searches,
    )

    searches = _queries_for_intent(
        query=search_text,
        normalized_query=query,
        intent=intent,
        max_searches=max_searches,
        authority_required=authority_required,
        freshness_required=freshness_required,
    )
    expected_source_types = _expected_source_types(
        query=query,
        intent=intent,
        authority_required=authority_required,
        freshness_required=freshness_required,
        primary_source_required=primary_source_required,
    )
    stop_criteria = _stop_criteria(
        intent=intent,
        authority_required=authority_required,
        max_searches=max_searches,
        max_extracts=max_extracts,
        search_count=len(searches),
    )
    subquestions = _subquestions_for_plan(
        searches=searches,
        intent=intent,
        expected_source_types=expected_source_types,
    )
    plan_id = _plan_id(
        query=query,
        intent=intent,
        searches=searches,
        expected_source_types=expected_source_types,
        stop_criteria=stop_criteria,
    )
    notes = [
        f"research_plan:{plan_id}",
        f"research_intent:{intent}",
        f"search_budget:{len(searches)}",
    ]
    if authority_required:
        notes.append("authority_required")
    if freshness_required:
        notes.append("freshness_required")
    if primary_source_required:
        notes.append("primary_source_required")
    notes.append(f"provider_strategy:{provider_strategy}")
    if max_extracts:
        notes.append(f"extract_top_results:{max_extracts}")

    return InternetScoutResearchPlan(
        plan_id=plan_id,
        intent=intent,
        searches=searches,
        subquestions=subquestions,
        expected_source_types=expected_source_types,
        authority_required=authority_required,
        freshness_required=freshness_required,
        primary_source_required=primary_source_required,
        max_searches=max_searches,
        provider_strategy=provider_strategy,
        search_providers=search_providers,
        max_extracts=max_extracts,
        stop_criteria=stop_criteria,
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


def _provider_strategy(
    *,
    request: InternetScoutRequest,
    selected_tool: InternetTool,
    max_searches: int,
) -> SearchProviderStrategy:
    if selected_tool != InternetTool.SEARCH or not request.query:
        return "auto"
    if request.requester.endswith(".deep_research") or max_searches > 1:
        return "fanout"
    return "auto"


def _max_extracts(
    *,
    request: InternetScoutRequest,
    selected_tool: InternetTool,
    authority_required: bool,
    freshness_required: bool,
    max_searches: int,
) -> int:
    if selected_tool != InternetTool.SEARCH or not request.query:
        return 0
    if request.requester.endswith(".deep_research"):
        return min(max(request.max_pages, 2), 4)
    if authority_required or freshness_required:
        return 1
    if max_searches > 1:
        return 1
    return 0


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
        planned.extend(_comparison_target_queries(query))
        if not any(item.purpose == "comparison" for item in planned):
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


def _expected_source_types(
    *,
    query: str,
    intent: ResearchIntent,
    authority_required: bool,
    freshness_required: bool,
    primary_source_required: bool,
) -> list[ResearchSourceType]:
    source_types: list[ResearchSourceType] = []
    if authority_required or intent == "official_docs":
        source_types.append("official_docs")
    if primary_source_required:
        source_types.append("primary_source")
    if freshness_required:
        source_types.append("release_notes")
    if "pricing" in query or "price" in query:
        source_types.append("pricing")
    if any(marker in query for marker in ("law", "legal", "regulation", "tax")):
        source_types.append("legal_regulatory")
    if "security advisory" in query or "cve" in query:
        source_types.append("security_advisory")
    if "status" in query:
        source_types.append("status_page")
    if not source_types:
        source_types.append("general_web")
    if "trusted_secondary" not in source_types and intent == "comparison":
        source_types.append("trusted_secondary")
    return _dedupe_source_types(source_types)[:8]


def _stop_criteria(
    *,
    intent: ResearchIntent,
    authority_required: bool,
    max_searches: int,
    max_extracts: int,
    search_count: int,
) -> InternetScoutResearchStopCriteria:
    require_cross_check = search_count > 1 and intent != "official_docs"
    min_accepted_citations = 1 if authority_required else 2 if search_count > 1 else 1
    min_source_hosts = 2 if require_cross_check or search_count > 1 else 1
    stop_when = [
        f"accepted_citations>={min_accepted_citations}",
        f"source_hosts>={min_source_hosts}",
        "unsupported_claims=0",
    ]
    if authority_required:
        stop_when.append("official_source_present")
    if require_cross_check:
        stop_when.append("cross_check_query_executed")
    return InternetScoutResearchStopCriteria(
        min_accepted_citations=min_accepted_citations,
        min_source_hosts=min_source_hosts,
        require_official_source=authority_required,
        require_cross_check=require_cross_check,
        max_searches=max_searches,
        max_extracts=max_extracts,
        stop_when=stop_when[:10],
    )


def _subquestions_for_plan(
    *,
    searches: list[InternetScoutResearchQuery],
    intent: ResearchIntent,
    expected_source_types: list[ResearchSourceType],
) -> list[InternetScoutResearchSubquestion]:
    if not searches:
        return []

    labels: dict[str, str] = {
        "baseline": "What direct evidence answers the user request?",
        "official_source": "Which official source establishes the answer?",
        "primary_source": "Which primary source corroborates the answer?",
        "recency": "What evidence proves the answer is current?",
        "comparison": "What evidence distinguishes the compared options?",
        "cross_check": "What independent source cross-checks the answer?",
    }
    subquestions: list[InternetScoutResearchSubquestion] = []
    for search in searches:
        subquestions.append(
            InternetScoutResearchSubquestion(
                question=labels.get(search.purpose, f"Research {intent}."),
                purpose=search.purpose,
                required=search.required,
                expected_source_types=expected_source_types,
            )
        )
    return subquestions[:6]


def _plan_id(
    *,
    query: str,
    intent: ResearchIntent,
    searches: list[InternetScoutResearchQuery],
    expected_source_types: list[ResearchSourceType],
    stop_criteria: InternetScoutResearchStopCriteria,
) -> str:
    payload = {
        "query": query,
        "intent": intent,
        "searches": [
            {
                "query": item.query,
                "purpose": item.purpose,
                "required": item.required,
            }
            for item in searches
        ],
        "expected_source_types": expected_source_types,
        "stop_criteria": stop_criteria.model_dump(mode="json"),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _official_site_query(*, query: str, normalized_query: str) -> str | None:
    hosts = _hosts_from_query(normalized_query)
    for target in _comparison_targets(query):
        hosts.extend(_official_hosts_for_target(target))
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


def _comparison_target_queries(query: str) -> list[InternetScoutResearchQuery]:
    targets = _comparison_targets(query)
    if len(targets) < 2:
        return [
            InternetScoutResearchQuery(
                query=_bounded_query(f"{query} official comparison documentation"),
                purpose="comparison",
            )
        ]

    searches: list[InternetScoutResearchQuery] = []
    for target in targets[:3]:
        target_query = f"{target} official documentation"
        hosts = _official_hosts_for_target(target)
        if hosts:
            site_filter = " OR ".join(f"site:{host}" for host in hosts[:3])
            target_query = f"{target_query} ({site_filter})"
        searches.append(
            InternetScoutResearchQuery(
                query=_bounded_query(target_query),
                purpose="comparison",
                required=True,
            )
        )
    return searches


def _comparison_targets(query: str) -> list[str]:
    scoped = re.sub(
        r"^\s*(?:compare|comparison\s+of)\s+",
        "",
        query,
        count=1,
        flags=re.IGNORECASE,
    )
    scoped = _COMPARISON_SCOPE_RE.split(scoped, maxsplit=1)[0]
    parts = _COMPARISON_SPLIT_RE.split(scoped)
    targets: list[str] = []
    for part in parts:
        target = _clean_comparison_target(part)
        if target:
            targets.append(target)
    if len(targets) < 2:
        return []
    return _dedupe_strings(targets)[:3]


def _clean_comparison_target(value: str) -> str:
    return re.sub(
        r"\b(?:cite|cited|independent|sources?|official|documentation|docs)\b",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip(" ,;:-")


def _official_hosts_for_target(target: str) -> list[str]:
    normalized = _normalize(target)
    hosts: list[str] = []
    if "brave" in normalized:
        hosts.extend(["brave.com", "api-dashboard.search.brave.com", "docs.brave.com"])
    if "perplexity" in normalized:
        hosts.extend(["perplexity.ai", "docs.perplexity.ai"])
    if "openai" in normalized:
        hosts.extend(["openai.com", "platform.openai.com", "docs.openai.com"])
    if "anthropic" in normalized:
        hosts.extend(["anthropic.com", "docs.anthropic.com"])
    if "github" in normalized:
        hosts.extend(["github.com", "docs.github.com"])
    if "cloudflare" in normalized:
        hosts.extend(["cloudflare.com", "developers.cloudflare.com"])
    if "aws" in normalized or "lambda" in normalized:
        hosts.extend(["aws.amazon.com", "docs.aws.amazon.com"])
    return _dedupe_strings(hosts)


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


def _dedupe_source_types(values: list[ResearchSourceType]) -> list[ResearchSourceType]:
    return list(dict.fromkeys(values))


def _normalize(value: str) -> str:
    return _collapse_whitespace(value).lower()


def _bounded_query(value: str) -> str:
    return value[:500].strip()


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
