from __future__ import annotations

from brain.services.internet_scout.models import InternetScoutRequest, InternetTool
from brain.services.internet_scout.orchestrator import InternetScoutOrchestrator
from brain.services.internet_scout.policy import evaluate_policy, select_tool


def test_select_tool_defaults_to_search_for_query_only_request():
    request = InternetScoutRequest(query="current source-backed fact")

    assert select_tool(request) == InternetTool.SEARCH


def test_fetch_policy_allows_safe_public_url_without_approval():
    request = InternetScoutRequest(urls=["https://public.example.test/article"])
    decision = evaluate_policy(request)

    assert decision.tool == InternetTool.FETCH
    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.tier == "T2"


def test_fetch_policy_blocks_internal_url():
    request = InternetScoutRequest(urls=["http://127.0.0.1:8000/secrets"])
    decision = evaluate_policy(request)

    assert decision.allowed is False
    assert "blocked_non_global_ip" in decision.blocked_reasons


def test_crawl_policy_enforces_depth_and_page_limits():
    too_many_pages = InternetScoutRequest(
        urls=["https://public.example.test"],
        max_pages=11,
    )
    too_deep = InternetScoutRequest(
        urls=["https://public.example.test"],
        max_depth=3,
    )

    assert (
        "crawl_page_limit_exceeded" in evaluate_policy(too_many_pages).blocked_reasons
    )
    assert "crawl_depth_limit_exceeded" in evaluate_policy(too_deep).blocked_reasons


def test_browser_use_is_disabled_and_requires_approval_in_p1():
    request = InternetScoutRequest(
        query="open the page and click through login",
        needs_interaction=True,
    )
    decision = evaluate_policy(request)

    assert decision.tool == InternetTool.BROWSER_USE
    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.tier == "T4"
    assert "browser_use_not_enabled" in decision.blocked_reasons


def test_browser_use_escalates_high_risk_work_to_t5():
    request = InternetScoutRequest(
        query="inspect a privacy data broker form",
        needs_interaction=True,
        sensitivity="privacy",
    )
    decision = evaluate_policy(request)

    assert decision.tier == "T5"


def test_orchestrator_enables_policy_allowed_gateway_execution():
    plan = InternetScoutOrchestrator().plan(
        InternetScoutRequest(query="find source-backed facts")
    )

    assert plan.execution_enabled is True
    assert plan.gateway_required is True
    assert plan.decision.allowed is True
    assert "Gateway-owned endpoints" in " ".join(plan.notes)
