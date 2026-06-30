#!/usr/bin/env python3
"""Smoke Beacon production readiness endpoints without printing secrets."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import quote, urlparse

DEFAULT_BASE_URL = "https://jarvis-brain.tail40ed36.ts.net:8186"
DEFAULT_TOKEN_SSH_TARGET = "jarvisbrain@jarvis-brain.tail40ed36.ts.net"
CRAWLER_SMOKE_URL = "https://example.com/"
BROWSER_CLICK_SMOKE_REQUEST = {
    "urls": ["https://httpbingo.org/links/2/0"],
    "browser_clicks": [
        {
            "selector": 'a[href="/links/2/1"]',
            "label": "Smoke same-host link",
            "expected_host": "httpbingo.org",
        }
    ],
    "max_pages": 1,
    "max_depth": 0,
    "needs_interaction": True,
    "sensitivity": "normal",
    "requester": "beacon_browser_action_deploy_smoke",
}
SOURCE_CONNECTOR_SMOKE_SPECS = (
    {
        "data_source_id": "pubmed-eutils",
        "query": "Use PubMed E-utilities to find GLP-1 treatment outcome studies.",
        "hosts": (
            "pubmed.ncbi.nlm.nih.gov",
            "www.ncbi.nlm.nih.gov",
            "pmc.ncbi.nlm.nih.gov",
        ),
    },
    {
        "data_source_id": "sec-edgar",
        "query": "Use SEC EDGAR to find Apple 10-K filing evidence.",
        "hosts": ("www.sec.gov", "sec.gov"),
    },
    {
        "data_source_id": "osv-dev",
        "query": "Use OSV to check CVE-2021-44228 vulnerability details.",
        "hosts": ("osv.dev",),
    },
    {
        "data_source_id": "cisa-kev",
        "query": "Use CISA KEV to check whether CVE-2021-44228 is exploited.",
        "hosts": ("www.cisa.gov", "cisa.gov"),
    },
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("ALPHA_BASE_URL", DEFAULT_BASE_URL),
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("BEACON_SMOKE_PROFILE", "ken"),
    )
    parser.add_argument(
        "--skip-agent",
        action="store_true",
        default=os.getenv("BEACON_SMOKE_SKIP_AGENT", "0") == "1",
    )
    parser.add_argument(
        "--skip-source-connectors",
        action="store_true",
        default=os.getenv("BEACON_SMOKE_SKIP_SOURCE_CONNECTORS", "0") == "1",
    )
    parser.add_argument(
        "--run-browser-click",
        action="store_true",
        default=os.getenv("BEACON_SMOKE_RUN_BROWSER_CLICK", "0") == "1",
    )
    parser.add_argument(
        "--token-ssh-target",
        default=os.getenv("BEACON_SMOKE_TOKEN_SSH_TARGET", DEFAULT_TOKEN_SSH_TARGET),
        help=(
            "SSH target used to generate a target-side smoke token when "
            "BEACON_SMOKE_TOKEN is not set."
        ),
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    token = _smoke_token(
        profile=args.profile,
        base_url=base_url,
        token_ssh_target=args.token_ssh_target,
    )
    results: dict[str, object] = {}

    health = _call_json("GET", base_url, "/v1/internet-scout/health", token)
    checks_payload = health.get("checks")
    results["health"] = {
        "status": health.get("status"),
        "checks": sorted(checks_payload.keys())
        if isinstance(checks_payload, dict)
        else [],
        "warning_checks": sorted(
            name
            for name, check in checks_payload.items()
            if isinstance(check, dict) and check.get("status") == "warning"
        )
        if isinstance(checks_payload, dict)
        else [],
    }
    results["gateway"] = _gateway_health_summary(checks_payload)
    browser_runtime = _health_check_metadata(checks_payload, "browser_runtime")
    if browser_runtime:
        browser_limits = {
            "runtime": browser_runtime.get("runtime"),
            "timeout_ms": browser_runtime.get("timeout_ms"),
            "max_steps": browser_runtime.get("max_steps"),
            "max_runs_per_hour": browser_runtime.get("max_runs_per_hour"),
        }
        results["browser_runtime_limits"] = browser_limits
        if _int(browser_runtime.get("timeout_ms")) > 60_000:
            _emit({"results": results, "error": "browser timeout cap missing"})
            return 6
        if _int(browser_runtime.get("max_steps")) > 5:
            _emit({"results": results, "error": "browser max-step cap missing"})
            return 7
        if _int(browser_runtime.get("max_runs_per_hour")) > 10:
            _emit({"results": results, "error": "browser hourly quota cap missing"})
            return 8
    if health.get("status") != "ok":
        _emit({"results": results, "error": "beacon health degraded"})
        return 2

    retention = _call_json(
        "GET",
        base_url,
        "/v1/internet-scout/retention/report",
        token,
    )
    results["retention"] = {
        "mode": retention.get("mode"),
        "old_request_count": retention.get("old_request_count"),
        "screenshot_file_count": retention.get("screenshot_file_count"),
    }
    if retention.get("mode") != "report_only":
        _emit({"results": results, "error": "retention mode is not report_only"})
        return 3

    try:
        results["crawler"] = _run_crawler_smoke(base_url, token)
    except RuntimeError as exc:
        _emit({"results": results, "error": f"crawler smoke failed: {exc}"})
        return 11

    if not args.skip_agent:
        agent = _call_json(
            "POST",
            base_url,
            "/v1/internet-scout/agent/run",
            token,
            {
                "query": "Beacon production smoke public search",
                "requester": "beacon_smoke",
            },
        )
        citations_payload = agent.get("citations")
        results["agent"] = {
            "status": agent.get("status"),
            "selected_tool": agent.get("selected_tool"),
            "request_id": agent.get("request_id"),
            "citation_count": len(citations_payload)
            if isinstance(citations_payload, list)
            else 0,
            "confidence": agent.get("confidence"),
            "raw_web_content_is_untrusted": agent.get("raw_web_content_is_untrusted"),
        }
        if agent.get("status") != "completed":
            _emit({"results": results, "error": "beacon agent smoke failed"})
            return 4
        if agent.get("raw_web_content_is_untrusted") is not True:
            _emit({"results": results, "error": "agent trust boundary missing"})
            return 5

        if not args.skip_source_connectors:
            source_connector_results = _run_source_connector_smokes(base_url, token)
            results["source_connectors"] = source_connector_results
            failed_connectors = [
                item
                for item in source_connector_results
                if item.get("status") != "completed" or not item.get("host_verified")
            ]
            if failed_connectors:
                _emit(
                    {
                        "results": results,
                        "error": "source connector smoke failed",
                    }
                )
                return 9

    if args.run_browser_click:
        try:
            results["browser_click"] = _run_browser_click_smoke(
                base_url,
                token,
                approval_token=_approval_token(
                    profile=args.profile,
                    base_url=base_url,
                    token_ssh_target=args.token_ssh_target,
                ),
            )
        except RuntimeError as exc:
            _emit({"results": results, "error": f"browser click smoke failed: {exc}"})
            return 10

    _emit({"results": results, "status": "passed"})
    return 0


def _smoke_token(
    *,
    profile: str,
    base_url: str,
    token_ssh_target: str | None,
) -> str:
    token = os.getenv("BEACON_SMOKE_TOKEN")
    if token:
        return token

    if _is_local_base_url(base_url):
        return _local_smoke_token(profile=profile)

    if token_ssh_target:
        generated = subprocess.check_output(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "StrictHostKeyChecking=no",
                token_ssh_target,
                "cd ~/jarvis-alpha && .venv/bin/python scripts/gen_test_token.py "
                f"{shlex.quote(profile)}",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if not generated:
            raise RuntimeError("target token generation returned no token")
        return generated

    raise RuntimeError(
        "set BEACON_SMOKE_TOKEN or BEACON_SMOKE_TOKEN_SSH_TARGET for production smoke"
    )


def _local_smoke_token(*, profile: str) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    python_bin = os.getenv("PYTHON_BIN", str(repo_root / ".venv/bin/python"))
    generated = subprocess.check_output(
        [python_bin, str(repo_root / "scripts/gen_test_token.py"), profile],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
    if not generated:
        raise RuntimeError("test token generation returned no token")
    return generated


def _approval_token(
    *,
    profile: str,
    base_url: str,
    token_ssh_target: str | None,
) -> str:
    token = os.getenv("BEACON_SMOKE_APPROVAL_TOKEN")
    if token:
        return token

    if _is_local_base_url(base_url):
        from scripts.financial_approval_operator import _mint_approval_token

        return _mint_approval_token(profile_id=profile)

    if token_ssh_target:
        generated = subprocess.check_output(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "StrictHostKeyChecking=no",
                token_ssh_target,
                "cd ~/jarvis-alpha && set -a && source ~/jarvis/.secrets && "
                "set +a && .venv/bin/python -c "
                + shlex.quote(
                    "from scripts.financial_approval_operator import "
                    "_mint_approval_token;"
                    f"print(_mint_approval_token(profile_id={profile!r}))"
                ),
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if not generated:
            raise RuntimeError("target approval token generation returned no token")
        return generated

    raise RuntimeError(
        "set BEACON_SMOKE_APPROVAL_TOKEN or BEACON_SMOKE_TOKEN_SSH_TARGET "
        "for browser click smoke"
    )


def _is_local_base_url(base_url: str) -> bool:
    return (
        "://localhost" in base_url
        or "://127.0.0.1" in base_url
        or "://[::1]" in base_url
    )


def _call_json(
    method: str,
    base_url: str,
    path: str,
    token: str,
    body: dict[str, object] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, object]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(
            request,
            context=ssl._create_unverified_context(),
            timeout=45,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {detail}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{method} {path} returned non-object JSON")
    return payload


def _run_crawler_smoke(base_url: str, token: str) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    for name, path, body, fields in (
        (
            "scrape",
            "/v1/internet-scout/crawler/scrape",
            {
                "url": CRAWLER_SMOKE_URL,
                "query": "example domain",
                "max_bytes": 200_000,
            },
            ("request_id", "canonical_url", "host", "text", "content_hash"),
        ),
        (
            "map",
            "/v1/internet-scout/crawler/map",
            {
                "url": CRAWLER_SMOKE_URL,
                "max_pages": 1,
                "max_depth": 0,
                "max_bytes": 200_000,
            },
            ("request_id", "seed_url", "seed_host", "page_count", "links"),
        ),
        (
            "crawl",
            "/v1/internet-scout/crawler/crawl",
            {
                "url": CRAWLER_SMOKE_URL,
                "max_pages": 1,
                "max_depth": 0,
                "max_bytes": 200_000,
            },
            ("request_id", "seed_url", "seed_host", "page_count", "links"),
        ),
        (
            "extract",
            "/v1/internet-scout/crawler/extract",
            {
                "url": CRAWLER_SMOKE_URL,
                "query": "example domain",
                "schema": {"domain": "example domain"},
                "max_bytes": 200_000,
            },
            ("request_id", "canonical_url", "host", "fields"),
        ),
    ):
        payload = _call_json("POST", base_url, path, token, body)
        missing = [field for field in fields if field not in payload]
        if missing:
            raise RuntimeError(f"{name} missing {','.join(missing)}")
        checks.append(
            {
                "name": name,
                "request_id": payload.get("request_id"),
                "host": payload.get("host") or payload.get("seed_host"),
                "cache_hit": payload.get("cache_hit"),
                "page_count": payload.get("page_count"),
                "link_count": payload.get("link_count"),
                "field_count": len(payload.get("fields", []))
                if isinstance(payload.get("fields"), list)
                else None,
            }
        )

    health = _call_json("GET", base_url, "/v1/internet-scout/health", token)
    crawler = (health.get("checks") or {}).get("crawler")
    if not isinstance(crawler, dict) or crawler.get("status") != "ok":
        raise RuntimeError("crawler health is not ok")
    metadata = (
        crawler.get("metadata") if isinstance(crawler.get("metadata"), dict) else {}
    )
    return {
        "url": CRAWLER_SMOKE_URL,
        "checks": checks,
        "health_status": crawler.get("status"),
        "request_count": metadata.get("request_count"),
        "failed_request_count": metadata.get("failed_request_count"),
        "blocked_host_count": metadata.get("blocked_host_count"),
    }


def _run_browser_click_smoke(
    base_url: str,
    token: str,
    *,
    approval_token: str,
) -> dict[str, object]:
    approval = _call_json(
        "POST",
        base_url,
        "/v1/internet-scout/browser-task/approval-request",
        token,
        BROWSER_CLICK_SMOKE_REQUEST,
    )
    queue_id = str(approval.get("approval_queue_id") or "")
    if not queue_id:
        raise RuntimeError("approval request did not return approval_queue_id")

    _call_json(
        "POST",
        base_url,
        f"/v1/approvals/{queue_id}/decide",
        token,
        {"decision": "approved"},
        extra_headers={"X-Approval-Token": approval_token},
    )
    run = _call_json(
        "POST",
        base_url,
        "/v1/internet-scout/browser-task/run-approved",
        token,
        {
            "approval_queue_id": queue_id,
            "browser_request": BROWSER_CLICK_SMOKE_REQUEST,
            "max_steps": 5,
            "require_screenshot": True,
        },
    )
    history = _call_json(
        "GET",
        base_url,
        f"/v1/internet-scout/browser-task/history?limit=50&q={quote(queue_id)}",
        token,
    )
    rows = history.get("history") if isinstance(history.get("history"), list) else []
    browser_run = next(
        (
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("event_type") == "browser_run"
            and row.get("status") == "succeeded"
        ),
        {},
    )
    click_seen = any(
        isinstance(row, dict)
        and row.get("event_type") == "browser_action"
        and row.get("action") == "click"
        and row.get("status") == "succeeded"
        for row in rows
    )
    approval_seen = any(
        isinstance(row, dict)
        and row.get("event_type") == "approval_request"
        and row.get("status") == "queued"
        for row in rows
    )
    action_audit_count = _int(browser_run.get("action_audit_count"))
    if run.get("status") != "completed":
        raise RuntimeError("browser run did not complete")
    if not approval_seen or not browser_run or not click_seen or action_audit_count < 1:
        raise RuntimeError("browser history did not include approval, run, and click")
    return {
        "status": run.get("status"),
        "approval_queue_id": queue_id,
        "request_id": run.get("request_id"),
        "observation_count": len(run.get("observations") or []),
        "action_audit_count": action_audit_count,
        "history_count": len(rows),
        "click_succeeded": True,
    }


def _run_source_connector_smokes(
    base_url: str,
    token: str,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for spec in SOURCE_CONNECTOR_SMOKE_SPECS:
        data_source_id = str(spec["data_source_id"])
        expected_hosts = tuple(str(host) for host in spec["hosts"])
        agent = _call_json(
            "POST",
            base_url,
            "/v1/internet-scout/agent/run",
            token,
            {
                "query": str(spec["query"]),
                "requester": f"beacon_smoke.{data_source_id}",
            },
        )
        citation_hosts = sorted(_citation_hosts(agent.get("citations")))
        host_verified = any(host in citation_hosts for host in expected_hosts)
        results.append(
            {
                "data_source_id": data_source_id,
                "status": agent.get("status"),
                "selected_tool": agent.get("selected_tool"),
                "request_id": agent.get("request_id"),
                "citation_count": len(citation_hosts),
                "citation_hosts": citation_hosts,
                "expected_hosts": list(expected_hosts),
                "host_verified": host_verified,
                "raw_web_content_is_untrusted": agent.get(
                    "raw_web_content_is_untrusted"
                ),
            }
        )
    return results


def _citation_hosts(citations_payload: object) -> set[str]:
    if not isinstance(citations_payload, list):
        return set()
    hosts: set[str] = set()
    for citation in citations_payload:
        if not isinstance(citation, dict):
            continue
        host = citation.get("host")
        if isinstance(host, str) and host.strip():
            hosts.add(host.strip().lower())
        for key in ("url", "source_url", "canonical_url"):
            value = citation.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            parsed_host = urlparse(value).hostname
            if parsed_host:
                hosts.add(parsed_host.lower())
    return hosts


def _health_check_metadata(
    checks_payload: object,
    check_name: str,
) -> dict[str, object]:
    if not isinstance(checks_payload, dict):
        return {}
    check = checks_payload.get(check_name)
    if not isinstance(check, dict):
        return {}
    metadata = check.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return 0


def _gateway_health_summary(checks_payload: object) -> dict[str, object]:
    if not isinstance(checks_payload, dict):
        return {}
    gateway = checks_payload.get("gateway")
    if not isinstance(gateway, dict):
        return {}
    metadata = gateway.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "status": gateway.get("status"),
        "primary_provider": metadata.get("primary_provider"),
        "provider_order": metadata.get("provider_order", []),
        "usable_provider_count": metadata.get("usable_provider_count"),
        "required_provider_count": metadata.get("required_provider_count"),
        "provider_redundancy_status": metadata.get("provider_redundancy_status"),
        "provider_warning_status": metadata.get("provider_warning_status"),
    }


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
