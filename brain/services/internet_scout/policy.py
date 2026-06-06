"""Beacon tool-selection and approval policy."""

from __future__ import annotations

from brain.services.internet_scout.models import (
    ApprovalTier,
    InternetScoutRequest,
    InternetTool,
    PolicyDecision,
)
from brain.services.internet_scout.safety import validate_url

CRAWL_MAX_PAGES_WITHOUT_APPROVAL = 10
CRAWL_MAX_DEPTH_WITHOUT_APPROVAL = 2
HIGH_RISK_SENSITIVITY = {"privacy", "legal", "financial", "minor"}


def select_tool(request: InternetScoutRequest) -> InternetTool:
    """Select the least-powerful tool that can satisfy the request shape."""
    if request.tool_hint is not None:
        return request.tool_hint
    if request.needs_interaction:
        return InternetTool.BROWSER_USE
    if request.max_pages > 1 or request.max_depth > 0:
        return InternetTool.CRAWL
    if request.urls:
        return InternetTool.FETCH
    return InternetTool.SEARCH


def evaluate_policy(request: InternetScoutRequest) -> PolicyDecision:
    tool = select_tool(request)

    if tool == InternetTool.SEARCH:
        if not request.query:
            return _blocked(tool, "Search requires a query.", ["missing_query"])
        return PolicyDecision(
            tool=tool,
            allowed=True,
            requires_approval=False,
            tier="T2",
            reason="Read-only public search discovery; no browser actions.",
        )

    if tool in (InternetTool.FETCH, InternetTool.EXTRACT):
        blocked = _blocked_url_reasons(request.urls)
        if blocked:
            return _blocked(tool, "URL safety check failed.", blocked)
        return PolicyDecision(
            tool=tool,
            allowed=True,
            requires_approval=False,
            tier="T2",
            reason="Read-only public URL retrieval via Gateway-owned egress.",
        )

    if tool == InternetTool.CRAWL:
        blocked = _blocked_url_reasons(request.urls)
        if blocked:
            return _blocked(tool, "Crawl seed URL safety check failed.", blocked)
        if request.max_pages > CRAWL_MAX_PAGES_WITHOUT_APPROVAL:
            return _blocked(
                tool,
                "Crawl page limit exceeds P1 safety cap.",
                ["crawl_page_limit_exceeded"],
                tier="T3",
            )
        if request.max_depth > CRAWL_MAX_DEPTH_WITHOUT_APPROVAL:
            return _blocked(
                tool,
                "Crawl depth exceeds P1 safety cap.",
                ["crawl_depth_limit_exceeded"],
                tier="T3",
            )
        return PolicyDecision(
            tool=tool,
            allowed=True,
            requires_approval=False,
            tier="T3",
            reason="Bounded read-only crawl; no login, forms, or browser actions.",
        )

    if tool == InternetTool.BROWSER_USE:
        tier: ApprovalTier = (
            "T5" if request.sensitivity in HIGH_RISK_SENSITIVITY else "T4"
        )
        return PolicyDecision(
            tool=tool,
            allowed=False,
            requires_approval=True,
            tier=tier,
            reason=(
                "Interactive browser work is disabled in P1 and must be routed "
                "through a later approval-gated browser-use path."
            ),
            blocked_reasons=["browser_use_not_enabled"],
        )

    raise ValueError(f"unsupported internet tool: {tool.value}")


def _blocked(
    tool: InternetTool,
    reason: str,
    blocked_reasons: list[str],
    *,
    tier: ApprovalTier = "T2",
) -> PolicyDecision:
    return PolicyDecision(
        tool=tool,
        allowed=False,
        requires_approval=False,
        tier=tier,
        reason=reason,
        blocked_reasons=blocked_reasons,
    )


def _blocked_url_reasons(urls: list[str]) -> list[str]:
    if not urls:
        return ["missing_url"]
    reasons: list[str] = []
    for url in urls:
        result = validate_url(url)
        if not result.allowed:
            reasons.extend(result.reasons)
    return sorted(set(reasons))
