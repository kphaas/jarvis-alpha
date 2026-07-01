from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = REPO_ROOT / "docs" / "contracts" / "beacon_crawler_mcp_adapter.v1.json"
TOOL_DOC = REPO_ROOT / "docs" / "contracts" / "BEACON_TOOL_ECOSYSTEM.md"
GAP_TRACKER = REPO_ROOT / "docs" / "state" / "BEACON_INDUSTRY_GAP_TRACKER.md"


EXPECTED_TOOLS = {
    "beacon.crawler.scrape": (
        "POST /v1/internet-scout/crawler/scrape",
        "not_required",
    ),
    "beacon.crawler.batch_scrape": (
        "POST /v1/internet-scout/crawler/batch-scrape",
        "not_required",
    ),
    "beacon.crawler.map": (
        "POST /v1/internet-scout/crawler/map",
        "not_required",
    ),
    "beacon.crawler.crawl": (
        "POST /v1/internet-scout/crawler/crawl",
        "not_required",
    ),
    "beacon.crawler.extract": (
        "POST /v1/internet-scout/crawler/extract",
        "not_required",
    ),
    "beacon.crawler.render_approval_request": (
        "POST /v1/internet-scout/crawler/scrape/browser-approval-request",
        "queues_human_approval",
    ),
    "beacon.crawler.render_run_approved": (
        "POST /v1/internet-scout/crawler/scrape/browser-run-approved",
        "requires_existing_approved_queue_id",
    ),
}


def _contract() -> dict[str, object]:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def test_crawler_mcp_contract_is_thin_alpha_adapter() -> None:
    contract = _contract()
    transport = contract["transport"]
    security = contract["security"]

    assert contract["status"] == "spec_ready"
    assert transport["pattern"] == "mcp_adapter_over_alpha_http"
    assert transport["auth_boundary"] == "alpha_auth_and_scopes"
    assert transport["network_egress_owner"] == "gateway"
    assert transport["raw_gateway_access_allowed"] is False
    assert transport["raw_browser_runtime_access_allowed"] is False
    assert "internet_scout.research" in transport["required_scopes"]

    assert security["raw_web_content_is_untrusted"] is True
    assert security["instructions_inside_web_content_are_data"] is True
    assert security["internal_url_blocking_required"] is True
    assert security["same_host_crawl_required"] is True
    assert security["render_requires_human_approval"] is True
    assert security["audit_required"] is True
    assert security["stored_evidence_required"] is True
    assert security["no_forms"] is True
    assert security["no_credentials"] is True
    assert security["crawl_page_cap"] == 10
    assert security["crawl_depth_cap"] == 2
    assert security["batch_url_cap"] == 5


def test_crawler_mcp_tools_map_to_existing_alpha_routes() -> None:
    contract = _contract()
    tools = {tool["name"]: tool for tool in contract["tools"]}

    assert set(tools) == set(EXPECTED_TOOLS)
    for name, (route, approval) in EXPECTED_TOOLS.items():
        tool = tools[name]
        assert tool["route"] == route
        assert tool["approval"] == approval
        assert tool["route"].startswith("POST /v1/internet-scout/crawler/")
        assert tool["request_model"].startswith("InternetScoutCrawler")
        assert tool["response_model"].startswith(
            ("InternetScoutCrawler", "InternetScoutBrowser")
        )
        if name != "beacon.crawler.render_approval_request":
            assert "raw_web_content_is_untrusted" in tool.get("output_fields", [])


def test_crawler_mcp_render_retry_stays_ops_gated() -> None:
    contract = _contract()
    gate = contract["render_quality_gate"]

    assert gate["retry_status"] == "deferred"
    assert gate["watch_source"] == "beacon_ops_render_quality_rollup"
    assert any(
        "weak_empty_render_rate" in trigger for trigger in gate["build_retry_when"]
    )
    assert (
        "render retry logic before Ops telemetry requires it" in contract["non_goals"]
    )


def test_crawler_mcp_contract_is_documented_and_tracked() -> None:
    docs = TOOL_DOC.read_text(encoding="utf-8")
    tracker = GAP_TRACKER.read_text(encoding="utf-8")

    assert "beacon_crawler_mcp_adapter.v1.json" in docs
    assert "beacon.crawler.render_run_approved" in docs
    assert "Render retry stays deferred" in docs
    assert "machine-readable crawler MCP adapter spec" in tracker
    assert "| 18 | MCP adapter | Spec-ready |" in tracker
