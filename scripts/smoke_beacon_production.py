#!/usr/bin/env python3
"""Smoke Beacon production readiness endpoints without printing secrets."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://jarvis-brain.tail40ed36.ts.net:8186"


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
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    token = _smoke_token(profile=args.profile)
    results: dict[str, object] = {}

    health = _call_json("GET", base_url, "/v1/internet-scout/health", token)
    checks_payload = health.get("checks")
    results["health"] = {
        "status": health.get("status"),
        "checks": sorted(checks_payload.keys())
        if isinstance(checks_payload, dict)
        else [],
    }
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


def _smoke_token(*, profile: str) -> str:
    token = (
        os.getenv("BEACON_SMOKE_TOKEN")
        or os.getenv("ALPHA_TEST_TOKEN")
        or os.getenv("ALPHA_SERVICE_TOKEN")
    )
    if token:
        return token

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


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
