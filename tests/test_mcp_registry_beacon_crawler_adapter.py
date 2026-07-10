from __future__ import annotations

from brain.middleware.approval_classes import classify_route, determine_risk_tier
from brain.routes import mcp_registry


def test_mcp_registry_includes_beacon_crawler_adapter(monkeypatch) -> None:
    monkeypatch.delenv("BEACON_CRAWLER_MCP_ADAPTER_ENABLED", raising=False)

    servers = {server["id"]: server for server in mcp_registry.mcp_servers()}
    beacon = servers["beacon-crawler"]

    assert beacon["status"] == "planned"
    assert beacon["endpoint"] == "alpha"
    assert beacon["runtime_enabled"] is False
    assert beacon["adapter_route"] == "/v1/security/mcp/adapters/beacon-crawler"
    assert "internet_scout.research" in beacon["permissions"]


def test_beacon_crawler_adapter_status_fails_closed_by_default(monkeypatch) -> None:
    monkeypatch.delenv("BEACON_CRAWLER_MCP_ADAPTER_ENABLED", raising=False)

    status = mcp_registry.beacon_crawler_adapter_status()

    assert status["enabled"] is False
    assert status["runtime_status"] == "disabled"
    assert status["invoke_enabled"] is False
    assert status["invoke_route"] is None
    assert status["contract_status"] == "spec_ready"
    assert status["tool_count"] == 7
    assert status["tool_boundary_schema_version"] == "mcp_tool_boundary.v1"
    assert status["result_boundary"] == {
        "schema_version": "mcp_tool_result_boundary.v1",
        "content_is_data": True,
        "instructions_inside_result_ignored": True,
        "raw_tool_output_is_untrusted": True,
        "raw_result_text_is_not_prompt_instruction": True,
    }
    assert len(status["tool_boundaries"]) == 7
    assert "runtime_execution_not_implemented" in status["blocked_by"]
    assert "BEACON_CRAWLER_MCP_ADAPTER_ENABLED=true" in status["blocked_by"]
    assert status["boundaries"]["alpha_auth_required"] is True
    assert status["boundaries"]["gateway_egress_only"] is True
    assert status["boundaries"]["render_requires_human_approval"] is True
    render = next(
        item
        for item in status["tool_boundaries"]
        if item["tool_name"] == "beacon.crawler.render_run_approved"
    )
    assert render["approval_required"] is True
    assert render["requires_existing_approval"] is True
    assert render["can_invoke_without_human_approval"] is False


def test_beacon_crawler_adapter_flag_does_not_enable_invocation(monkeypatch) -> None:
    monkeypatch.setenv("BEACON_CRAWLER_MCP_ADAPTER_ENABLED", "true")

    status = mcp_registry.beacon_crawler_adapter_status()

    assert status["enabled"] is True
    assert status["runtime_status"] == "blocked_unimplemented"
    assert status["invoke_enabled"] is False
    assert status["blocked_by"] == ["runtime_execution_not_implemented"]
    assert status["tool_boundaries"]


def test_beacon_crawler_adapter_route_is_classified_read_only() -> None:
    classes = classify_route("GET", "/v1/security/mcp/adapters/beacon-crawler")

    assert classes == ["read", "security_read"]
    assert determine_risk_tier(classes) == "T2"
