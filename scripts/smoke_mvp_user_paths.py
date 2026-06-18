#!/usr/bin/env python3
"""Live smoke the Alpha MVP user paths without printing secrets.

This script is intentionally operator-facing and live-only. It proves:

1. Home weather resolves from Alpha settings and reads through Gateway.
2. Beacon web search and deep research return cited evidence.
3. Browser-use work queues for approval and does not run before approval.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shlex
import ssl
import subprocess
import sys
from typing import Any
import urllib.error
import urllib.request

DEFAULT_BRAIN_BASE_URL = "https://jarvis-brain.tail40ed36.ts.net:8186"
DEFAULT_BRAIN_SSH_TARGET = "jarvisbrain@jarvis-brain.tail40ed36.ts.net"
DEFAULT_PROFILE = "ken"


@dataclass(frozen=True)
class SmokeResult:
    status: str
    detail: dict[str, Any]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("ALPHA_BRAIN_BASE_URL", DEFAULT_BRAIN_BASE_URL),
        help="Brain base URL to probe.",
    )
    parser.add_argument(
        "--brain-ssh-target",
        default=os.getenv("JARVIS_ALPHA_BRAIN_SSH", DEFAULT_BRAIN_SSH_TARGET),
        help="SSH target used for Brain-side weather and DB verification.",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("MVP_USER_PATH_SMOKE_PROFILE", DEFAULT_PROFILE),
        help="Profile name passed to scripts/gen_test_token.py.",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("MVP_USER_PATH_SMOKE_TOKEN"),
        help="Optional pre-generated Brain bearer token.",
    )
    parser.add_argument(
        "--skip-browser-db-verify",
        action="store_true",
        help="Skip DB verification that browser work remained queued.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    results: dict[str, SmokeResult] = {}

    results["weather_home"] = _home_weather_check(args.brain_ssh_target)

    token = _smoke_token(
        explicit_token=args.token,
        profile=args.profile,
        base_url=base_url,
        brain_ssh_target=args.brain_ssh_target,
    )
    results["beacon_web_search"] = _internet_scout_check(
        base_url=base_url,
        token=token,
        name="beacon_web_search",
        body={
            "query": "Open-Meteo current weather API official documentation",
            "requester": "mvp_user_path.web_search",
            "tool_hint": "search",
        },
        min_citations=1,
    )
    results["beacon_deep_research"] = _internet_scout_check(
        base_url=base_url,
        token=token,
        name="beacon_deep_research",
        body={
            "query": (
                "Compare Brave Search API and Perplexity Search API pricing "
                "using current official docs"
            ),
            "requester": "mvp_user_path.deep_research",
            "tool_hint": "search",
            "max_pages": 4,
        },
        min_citations=1,
    )

    browser = _browser_approval_check(base_url=base_url, token=token)
    if browser.status == "passed" and not args.skip_browser_db_verify:
        request_id = browser.detail.get("request_id")
        approval_queue_id = browser.detail.get("approval_queue_id")
        if isinstance(request_id, str) and isinstance(approval_queue_id, str):
            browser_db = _browser_db_verification(
                brain_ssh_target=args.brain_ssh_target,
                request_id=request_id,
                approval_queue_id=approval_queue_id,
            )
            browser = _merge_browser_results(browser, browser_db)
        else:
            browser = SmokeResult(
                "failed",
                {**browser.detail, "db_verification": "missing request or queue id"},
            )
    results["browser_approval_queue"] = browser

    failures = [name for name, result in results.items() if result.status != "passed"]
    status = "passed" if not failures else "failed"
    _emit(
        {
            "status": status,
            "checks": {name: asdict(result) for name, result in results.items()},
        }
    )
    return 0 if status == "passed" else 2


def _home_weather_check(brain_ssh_target: str) -> SmokeResult:
    try:
        payload = _run_brain_python(brain_ssh_target, _WEATHER_REMOTE_PY)
    except Exception as exc:
        return SmokeResult("failed", {"error": _safe_error(exc)})
    return SmokeResult(
        "passed" if _home_weather_passed(payload) else "failed",
        _home_weather_summary(payload),
    )


def _home_weather_passed(payload: dict[str, Any]) -> bool:
    return (
        payload.get("status") == "passed"
        and payload.get("settings_home_coordinates_configured") is True
        and payload.get("weather_status") == "ok"
        and payload.get("provider") == "open-meteo"
        and payload.get("temperature_f_present") is True
        and payload.get("observed_at_present") is True
    )


def _home_weather_summary(payload: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "settings_home_coordinates_configured",
        "weather_status",
        "provider",
        "location_label",
        "condition",
        "temperature_f_present",
        "observed_at_present",
        "cached",
    )
    return {key: payload.get(key) for key in keys if key in payload}


def _internet_scout_check(
    *,
    base_url: str,
    token: str,
    name: str,
    body: dict[str, Any],
    min_citations: int,
) -> SmokeResult:
    try:
        payload = _call_json(
            "POST",
            base_url,
            "/v1/internet-scout/agent/run",
            token,
            body,
            timeout=90,
        )
    except Exception as exc:
        return SmokeResult("failed", {"name": name, "error": _safe_error(exc)})

    summary = _internet_scout_summary(payload)
    passed = (
        payload.get("status") == "completed"
        and summary["citation_count"] >= min_citations
        and summary["source_count"] >= 1
        and payload.get("raw_web_content_is_untrusted") is True
    )
    return SmokeResult("passed" if passed else "failed", summary)


def _internet_scout_summary(payload: dict[str, Any]) -> dict[str, Any]:
    citations = payload.get("citations")
    citation_count = len(citations) if isinstance(citations, list) else 0
    evidence = payload.get("evidence")
    sources = evidence.get("sources") if isinstance(evidence, dict) else None
    source_count = len(sources) if isinstance(sources, list) else 0
    research_report = payload.get("research_report")
    first_source_host = None
    if isinstance(sources, list) and sources and isinstance(sources[0], dict):
        first_source_host = sources[0].get("host")
    return {
        "response_status": payload.get("status"),
        "selected_tool": payload.get("selected_tool"),
        "request_id": payload.get("request_id"),
        "citation_count": citation_count,
        "source_count": source_count,
        "source_quality_status": payload.get("source_quality_status"),
        "confidence": payload.get("confidence"),
        "raw_web_content_is_untrusted": payload.get("raw_web_content_is_untrusted"),
        "research_report_mode": research_report.get("mode")
        if isinstance(research_report, dict)
        else None,
        "first_source_host": first_source_host,
    }


def _browser_approval_check(*, base_url: str, token: str) -> SmokeResult:
    body = {
        "query": "Open https://example.com and report the page title",
        "requester": "mvp_user_path.browser_approval",
        "tool_hint": "browser_use",
        "needs_interaction": True,
    }
    try:
        payload = _call_json(
            "POST",
            base_url,
            "/v1/internet-scout/browser-task/approval-request",
            token,
            body,
            timeout=45,
        )
    except Exception as exc:
        return SmokeResult("failed", {"error": _safe_error(exc)})

    summary = _browser_approval_summary(payload)
    return SmokeResult(
        "passed" if _browser_approval_passed(summary) else "failed",
        summary,
    )


def _browser_approval_summary(payload: dict[str, Any]) -> dict[str, Any]:
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        plan = {}
    decision = plan.get("decision")
    if not isinstance(decision, dict):
        decision = {}
    return {
        "request_id": payload.get("request_id"),
        "approval_queue_id": payload.get("approval_queue_id"),
        "approval_status": payload.get("approval_status"),
        "selected_tool": decision.get("tool") or plan.get("selected_tool"),
        "requires_approval": decision.get("requires_approval"),
        "risk_tier": decision.get("tier"),
    }


def _browser_approval_passed(summary: dict[str, Any]) -> bool:
    return (
        isinstance(summary.get("request_id"), str)
        and isinstance(summary.get("approval_queue_id"), str)
        and summary.get("approval_status") == "pending"
        and summary.get("selected_tool") == "browser_use"
        and summary.get("requires_approval") is True
        and summary.get("risk_tier") == "T4"
    )


def _browser_db_verification(
    *,
    brain_ssh_target: str,
    request_id: str,
    approval_queue_id: str,
) -> SmokeResult:
    command_prefix = (
        f"REQ_ID={shlex.quote(request_id)} "
        f"QUEUE_ID={shlex.quote(approval_queue_id)} "
    )
    try:
        payload = _run_brain_python(
            brain_ssh_target,
            _BROWSER_DB_REMOTE_PY,
            command_prefix=command_prefix,
        )
    except Exception as exc:
        return SmokeResult("failed", {"error": _safe_error(exc)})
    return SmokeResult(
        "passed" if _browser_db_verification_passed(payload) else "failed",
        payload,
    )


def _browser_db_verification_passed(payload: dict[str, Any]) -> bool:
    return (
        payload.get("status") == "passed"
        and payload.get("browser_run_event_count") == 0
    )


def _merge_browser_results(
    browser: SmokeResult,
    browser_db: SmokeResult,
) -> SmokeResult:
    detail = {**browser.detail, "db_verification": browser_db.detail}
    return SmokeResult(
        "passed" if browser.status == "passed" and browser_db.status == "passed" else "failed",
        detail,
    )


def _smoke_token(
    *,
    explicit_token: str | None,
    profile: str,
    base_url: str,
    brain_ssh_target: str,
) -> str:
    if explicit_token:
        return explicit_token
    if _is_local_base_url(base_url):
        return _local_smoke_token(profile=profile)
    generated = subprocess.check_output(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "StrictHostKeyChecking=no",
            brain_ssh_target,
            "cd ~/jarvis-alpha && .venv/bin/python scripts/gen_test_token.py "
            f"{shlex.quote(profile)}",
        ],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
    if not generated:
        raise RuntimeError("target token generation returned no token")
    return generated


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


def _run_brain_python(
    brain_ssh_target: str,
    source: str,
    *,
    command_prefix: str = "",
) -> dict[str, Any]:
    remote_command = (
        "cd ~/jarvis-alpha && "
        "set -a && source ~/jarvis/.secrets && set +a && "
        f"{command_prefix}.venv/bin/python -"
    )
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "StrictHostKeyChecking=no",
            brain_ssh_target,
            remote_command,
        ],
        input=source,
        text=True,
        capture_output=True,
        check=False,
        timeout=90,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ssh python failed with exit {result.returncode}: "
            f"{_truncate(result.stderr or result.stdout)}"
        )
    return _parse_json_from_stdout(result.stdout)


def _parse_json_from_stdout(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise RuntimeError("remote command did not emit JSON object")


def _call_json(
    method: str,
    base_url: str,
    path: str,
    token: str,
    body: dict[str, Any] | None,
    *,
    timeout: int,
) -> dict[str, Any]:
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
            timeout=timeout,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {detail}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{method} {path} returned non-object JSON")
    return payload


def _is_local_base_url(base_url: str) -> bool:
    return (
        "://localhost" in base_url
        or "://127.0.0.1" in base_url
        or "://[::1]" in base_url
    )


def _safe_error(exc: BaseException) -> str:
    return _truncate(str(exc))


def _truncate(value: str, limit: int = 800) -> str:
    return value if len(value) <= limit else value[: limit - 3] + "..."


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


_WEATHER_REMOTE_PY = r'''
import asyncio
import json

from brain.core.config import ALPHA_DB_DSN_WRITER
from brain.db.pool import init_pool, close_pool
from brain.services.web_agent_settings import get_home_weather_coordinates
from brain.services.weather_client import get_current_weather


async def main():
    await init_pool(ALPHA_DB_DSN_WRITER)
    try:
        coords = await get_home_weather_coordinates()
        result = await get_current_weather({"location_label": "home"})
        print(json.dumps({
            "status": "passed"
            if result.get("status") == "ok" and coords is not None
            else "failed",
            "settings_home_coordinates_configured": coords is not None,
            "weather_status": result.get("status"),
            "provider": result.get("provider"),
            "location_label": result.get("location_label"),
            "condition": result.get("condition"),
            "temperature_f_present": result.get("temperature_f") is not None,
            "observed_at_present": result.get("observed_at") is not None,
            "cached": result.get("cached"),
        }, sort_keys=True))
    finally:
        await close_pool()


asyncio.run(main())
'''


_BROWSER_DB_REMOTE_PY = r'''
import asyncio
import json
import os
from uuid import UUID

from brain.core.config import ALPHA_DB_DSN_WRITER
from brain.db.pool import init_pool, close_pool
from brain.db.rls import platform_admin_connection


def metadata_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


async def main():
    await init_pool(ALPHA_DB_DSN_WRITER)
    try:
        request_id = UUID(os.environ["REQ_ID"])
        queue_id = UUID(os.environ["QUEUE_ID"])
        async with platform_admin_connection(
            source="test",
            audit_actor="mvp_user_path_smoke",
        ) as conn:
            approval = await conn.fetchrow(
                """
                SELECT id, status, risk_tier, actor_type, action_class,
                       expires_at > NOW() AS unexpired
                FROM public.alpha_approval_queue
                WHERE id = $1
                """,
                queue_id,
            )
            events = await conn.fetch(
                """
                SELECT tool, event_type, status, metadata
                FROM public.alpha_internet_tool_events
                WHERE request_id = $1
                ORDER BY created_at ASC
                """,
                request_id,
            )
            browser_run_count = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM public.alpha_internet_tool_events
                WHERE request_id = $1
                  AND tool = $2
                  AND event_type = $3
                """,
                request_id,
                "browser_use",
                "browser_run",
            )

        event_summary = []
        for row in events:
            metadata = metadata_dict(row["metadata"])
            event_summary.append({
                "tool": row["tool"],
                "event_type": row["event_type"],
                "status": row["status"],
                "approval_queue_id": metadata.get("approval_queue_id"),
                "requires_approval": metadata.get("requires_approval"),
            })
        passed = bool(
            approval
            and approval["status"] == "pending"
            and approval["risk_tier"] == "T4"
            and approval["unexpired"] is True
            and any(
                row["tool"] == "browser_use"
                and row["event_type"] == "approval_request"
                and row["status"] == "queued"
                and row["approval_queue_id"] == str(queue_id)
                and row["requires_approval"] is True
                for row in event_summary
            )
            and int(browser_run_count or 0) == 0
        )
        print(json.dumps({
            "status": "passed" if passed else "failed",
            "approval_queue": dict(approval) if approval else None,
            "events": event_summary,
            "browser_run_event_count": int(browser_run_count or 0),
        }, default=str, sort_keys=True))
    finally:
        await close_pool()


asyncio.run(main())
'''


if __name__ == "__main__":
    raise SystemExit(main())
