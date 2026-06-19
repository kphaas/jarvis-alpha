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

DEFAULT_BASE_URL = "https://jarvis-brain.tail40ed36.ts.net:8186"
DEFAULT_TOKEN_SSH_TARGET = "jarvisbrain@jarvis-brain.tail40ed36.ts.net"


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
) -> dict[str, object]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
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
