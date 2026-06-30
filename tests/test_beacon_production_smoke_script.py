from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path("scripts/smoke_beacon_production.py")
SPEC = importlib.util.spec_from_file_location("smoke_beacon_production", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
smoke_beacon_production = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke_beacon_production)


def test_smoke_token_uses_explicit_beacon_token(monkeypatch):
    monkeypatch.setenv("BEACON_SMOKE_TOKEN", "beacon-token")
    monkeypatch.setenv("ALPHA_TEST_TOKEN", "stale-test-token")
    monkeypatch.setenv("ALPHA_SERVICE_TOKEN", "stale-service-token")

    token = smoke_beacon_production._smoke_token(
        profile="ken",
        base_url=smoke_beacon_production.DEFAULT_BASE_URL,
        token_ssh_target=None,
    )

    assert token == "beacon-token"


def test_smoke_token_uses_target_side_generation(monkeypatch):
    monkeypatch.delenv("BEACON_SMOKE_TOKEN", raising=False)
    monkeypatch.setenv("ALPHA_TEST_TOKEN", "stale-test-token")
    monkeypatch.setenv("ALPHA_SERVICE_TOKEN", "stale-service-token")
    calls: list[list[str]] = []

    def fake_check_output(cmd, *, text, stderr):
        calls.append(cmd)
        return "target-token\n"

    monkeypatch.setattr(
        smoke_beacon_production.subprocess,
        "check_output",
        fake_check_output,
    )

    token = smoke_beacon_production._smoke_token(
        profile="ken",
        base_url=smoke_beacon_production.DEFAULT_BASE_URL,
        token_ssh_target="jarvisbrain@example.test",
    )

    assert token == "target-token"
    assert calls[0][0] == "ssh"
    assert calls[0][-2] == "jarvisbrain@example.test"
    assert "scripts/gen_test_token.py ken" in calls[0][-1]


def test_remote_smoke_without_token_source_fails_explicitly(monkeypatch):
    monkeypatch.delenv("BEACON_SMOKE_TOKEN", raising=False)
    monkeypatch.setenv("ALPHA_TEST_TOKEN", "stale-test-token")
    monkeypatch.setenv("ALPHA_SERVICE_TOKEN", "stale-service-token")

    with pytest.raises(RuntimeError, match="BEACON_SMOKE_TOKEN"):
        smoke_beacon_production._smoke_token(
            profile="ken",
            base_url=smoke_beacon_production.DEFAULT_BASE_URL,
            token_ssh_target=None,
        )


def test_approval_token_prefers_explicit_env(monkeypatch):
    monkeypatch.setenv("BEACON_SMOKE_APPROVAL_TOKEN", "approval-token")

    token = smoke_beacon_production._approval_token(
        profile="ken",
        base_url=smoke_beacon_production.DEFAULT_BASE_URL,
        token_ssh_target=None,
    )

    assert token == "approval-token"


def test_health_check_metadata_extracts_browser_runtime_limits():
    metadata = smoke_beacon_production._health_check_metadata(
        {
            "browser_runtime": {
                "status": "ok",
                "metadata": {
                    "runtime": "playwright",
                    "timeout_ms": 20_000,
                    "max_steps": 5,
                    "max_runs_per_hour": 3,
                },
            }
        },
        "browser_runtime",
    )

    assert metadata["max_steps"] == 5
    assert smoke_beacon_production._int(metadata["timeout_ms"]) == 20_000


def test_health_check_metadata_missing_check_is_empty():
    assert smoke_beacon_production._health_check_metadata({}, "browser_runtime") == {}
    assert smoke_beacon_production._int("not-a-number") == 0


def test_gateway_health_summary_surfaces_provider_route():
    summary = smoke_beacon_production._gateway_health_summary(
        {
            "gateway": {
                "status": "ok",
                "metadata": {
                    "primary_provider": "searxng",
                    "provider_order": ["searxng", "brave"],
                    "usable_provider_count": 2,
                    "required_provider_count": 2,
                    "provider_redundancy_status": "redundant",
                    "provider_warning_status": None,
                },
            }
        }
    )

    assert summary == {
        "status": "ok",
        "primary_provider": "searxng",
        "provider_order": ["searxng", "brave"],
        "usable_provider_count": 2,
        "required_provider_count": 2,
        "provider_redundancy_status": "redundant",
        "provider_warning_status": None,
    }


def test_citation_hosts_extracts_host_fields_and_urls():
    hosts = smoke_beacon_production._citation_hosts(
        [
            {"host": "OSV.dev"},
            {"source_url": "https://pubmed.ncbi.nlm.nih.gov/12345/"},
            {"canonical_url": "https://www.sec.gov/Archives/example.htm"},
            {"url": "not a url"},
        ]
    )

    assert hosts == {"osv.dev", "pubmed.ncbi.nlm.nih.gov", "www.sec.gov"}


def test_source_connector_smoke_verifies_expected_citation_host(monkeypatch):
    monkeypatch.setattr(
        smoke_beacon_production,
        "SOURCE_CONNECTOR_SMOKE_SPECS",
        (
            {
                "data_source_id": "osv-dev",
                "query": "Use OSV to check CVE-2021-44228.",
                "hosts": ("osv.dev",),
            },
        ),
    )

    def fake_call_json(method, base_url, path, token, body=None):
        assert method == "POST"
        assert path == "/v1/internet-scout/agent/run"
        assert body["requester"] == "beacon_smoke.osv-dev"
        return {
            "status": "completed",
            "selected_tool": "search",
            "request_id": "request-1",
            "citations": [{"source_url": "https://osv.dev/vulnerability/CVE-1"}],
            "raw_web_content_is_untrusted": True,
        }

    monkeypatch.setattr(smoke_beacon_production, "_call_json", fake_call_json)

    results = smoke_beacon_production._run_source_connector_smokes(
        "https://alpha.example.test",
        "token",
    )

    assert results == [
        {
            "data_source_id": "osv-dev",
            "status": "completed",
            "selected_tool": "search",
            "request_id": "request-1",
            "citation_count": 1,
            "citation_hosts": ["osv.dev"],
            "expected_hosts": ["osv.dev"],
            "host_verified": True,
            "raw_web_content_is_untrusted": True,
        }
    ]


def test_crawler_smoke_checks_four_endpoints_and_health(monkeypatch):
    calls = []

    def fake_call_json(method, base_url, path, token, body=None):
        calls.append((method, path, body))
        if path == "/v1/internet-scout/crawler/scrape":
            return {
                "request_id": "scrape-1",
                "canonical_url": "https://example.com/",
                "host": "example.com",
                "text": "Example Domain",
                "content_hash": "a" * 64,
            }
        if path in {
            "/v1/internet-scout/crawler/map",
            "/v1/internet-scout/crawler/crawl",
        }:
            return {
                "request_id": path.rsplit("/", 1)[-1] + "-1",
                "seed_url": "https://example.com/",
                "seed_host": "example.com",
                "page_count": 1,
                "link_count": 0,
                "links": [],
            }
        if path == "/v1/internet-scout/crawler/extract":
            return {
                "request_id": "extract-1",
                "canonical_url": "https://example.com/",
                "host": "example.com",
                "fields": [{"field": "domain", "found": True}],
            }
        if path == "/v1/internet-scout/health":
            return {
                "checks": {
                    "crawler": {
                        "status": "ok",
                        "metadata": {
                            "request_count": 4,
                            "failed_request_count": 0,
                            "blocked_host_count": 0,
                        },
                    }
                }
            }
        raise AssertionError(path)

    monkeypatch.setattr(smoke_beacon_production, "_call_json", fake_call_json)

    result = smoke_beacon_production._run_crawler_smoke(
        "https://alpha.example.test",
        "token",
    )

    assert result["health_status"] == "ok"
    assert result["failed_request_count"] == 0
    assert [item["name"] for item in result["checks"]] == [
        "scrape",
        "map",
        "crawl",
        "extract",
    ]
    assert [call[1] for call in calls] == [
        "/v1/internet-scout/crawler/scrape",
        "/v1/internet-scout/crawler/map",
        "/v1/internet-scout/crawler/crawl",
        "/v1/internet-scout/crawler/extract",
        "/v1/internet-scout/health",
    ]
    assert calls[0][2]["max_bytes"] == 200_000
    assert calls[1][2]["max_pages"] == 1


def test_browser_click_smoke_approves_runs_and_checks_history(monkeypatch):
    calls = []

    def fake_call_json(method, base_url, path, token, body=None, extra_headers=None):
        calls.append((method, path, body, extra_headers))
        if path == "/v1/internet-scout/browser-task/approval-request":
            return {"approval_queue_id": "queue-1"}
        if path == "/v1/approvals/queue-1/decide":
            assert extra_headers == {"X-Approval-Token": "approval-token"}
            assert body == {"decision": "approved"}
            return {"decision": "approved"}
        if path == "/v1/internet-scout/browser-task/run-approved":
            assert body["max_steps"] == 5
            assert body["require_screenshot"] is True
            return {
                "status": "completed",
                "request_id": "request-1",
                "observations": [{"host": "httpbingo.org"}],
            }
        if path == "/v1/internet-scout/browser-task/history?limit=50&q=queue-1":
            return {
                "history": [
                    {"event_type": "approval_request", "status": "queued"},
                    {
                        "event_type": "browser_run",
                        "status": "succeeded",
                        "action_audit_count": 3,
                    },
                    {
                        "event_type": "browser_action",
                        "status": "succeeded",
                        "action": "click",
                    },
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(smoke_beacon_production, "_call_json", fake_call_json)

    result = smoke_beacon_production._run_browser_click_smoke(
        "https://alpha.example.test",
        "token",
        approval_token="approval-token",
    )

    assert result["click_succeeded"] is True
    assert result["action_audit_count"] == 3
    assert [call[1] for call in calls] == [
        "/v1/internet-scout/browser-task/approval-request",
        "/v1/approvals/queue-1/decide",
        "/v1/internet-scout/browser-task/run-approved",
        "/v1/internet-scout/browser-task/history?limit=50&q=queue-1",
    ]


def test_source_connector_smoke_accepts_pubmed_ncbi_alias_hosts(monkeypatch):
    monkeypatch.setattr(
        smoke_beacon_production,
        "SOURCE_CONNECTOR_SMOKE_SPECS",
        (
            {
                "data_source_id": "pubmed-eutils",
                "query": "Use PubMed E-utilities to find GLP-1 outcomes.",
                "hosts": (
                    "pubmed.ncbi.nlm.nih.gov",
                    "www.ncbi.nlm.nih.gov",
                    "pmc.ncbi.nlm.nih.gov",
                ),
            },
        ),
    )

    def fake_call_json(method, base_url, path, token, body=None):
        assert method == "POST"
        assert path == "/v1/internet-scout/agent/run"
        assert body["requester"] == "beacon_smoke.pubmed-eutils"
        return {
            "status": "completed",
            "selected_tool": "search",
            "request_id": "request-pubmed",
            "citations": [
                {"source_url": ("https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/")}
            ],
            "raw_web_content_is_untrusted": True,
        }

    monkeypatch.setattr(smoke_beacon_production, "_call_json", fake_call_json)

    results = smoke_beacon_production._run_source_connector_smokes(
        "https://alpha.example.test",
        "token",
    )

    assert results == [
        {
            "data_source_id": "pubmed-eutils",
            "status": "completed",
            "selected_tool": "search",
            "request_id": "request-pubmed",
            "citation_count": 1,
            "citation_hosts": ["pmc.ncbi.nlm.nih.gov"],
            "expected_hosts": [
                "pubmed.ncbi.nlm.nih.gov",
                "www.ncbi.nlm.nih.gov",
                "pmc.ncbi.nlm.nih.gov",
            ],
            "host_verified": True,
            "raw_web_content_is_untrusted": True,
        }
    ]
