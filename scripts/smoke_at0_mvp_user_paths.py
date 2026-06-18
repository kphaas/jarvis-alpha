#!/usr/bin/env python3
"""Live smoke the AT-0 front-door MVP user paths without printing secrets.

This script proves the user-facing Alpha chat endpoint carries Beacon internet
metadata for MVP web paths, and that browser-use work appears in the operator
approval queue instead of executing automatically.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shlex
import ssl
import subprocess
import sys
import time
from typing import Any
import urllib.error
import urllib.request

DEFAULT_BRAIN_BASE_URL = "https://jarvis-brain.tail40ed36.ts.net:8186"
DEFAULT_TOKEN_SSH_TARGET = "jarvisbrain@jarvis-brain.tail40ed36.ts.net"
DEFAULT_PROFILE = "ken"


@dataclass(frozen=True)
class ChatSmokeCase:
    name: str
    prompt: str
    internet_mode: str
    expected_any_hosts: tuple[str, ...] = ()
    min_citations: int = 1
    min_planned_query_count: int = 0
    min_independent_source_count: int = 0
    require_synthesis_citations: bool = True


@dataclass(frozen=True)
class SmokeResult:
    status: str
    detail: dict[str, Any]


CHAT_CASES = (
    ChatSmokeCase(
        name="chat_weather_web_search",
        prompt="What is the weather outside right now? Use my home location if configured.",
        internet_mode="web_search",
        expected_any_hosts=("open-meteo.com", "api.open-meteo.com"),
        require_synthesis_citations=False,
    ),
    ChatSmokeCase(
        name="chat_deep_research",
        prompt=(
            "Compare Brave Search API and Perplexity Search API pricing using "
            "current official docs."
        ),
        internet_mode="deep_research",
        expected_any_hosts=("brave.com", "perplexity.ai"),
        min_planned_query_count=1,
        min_independent_source_count=1,
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("AT0_MVP_SMOKE_BASE_URL", DEFAULT_BRAIN_BASE_URL),
        help="Brain base URL to probe.",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("AT0_MVP_SMOKE_PROFILE", DEFAULT_PROFILE),
        help="Profile name passed to scripts/gen_test_token.py.",
    )
    parser.add_argument(
        "--token",
        default=(
            os.getenv("AT0_MVP_SMOKE_TOKEN")
            or os.getenv("MVP_USER_PATH_SMOKE_TOKEN")
            or os.getenv("HELM_ASK_SMOKE_TOKEN")
            or os.getenv("BEACON_SMOKE_TOKEN")
        ),
        help="Optional pre-generated Brain bearer token.",
    )
    parser.add_argument(
        "--token-ssh-target",
        default=os.getenv("AT0_MVP_SMOKE_TOKEN_SSH_TARGET", DEFAULT_TOKEN_SSH_TARGET),
        help="SSH target used to generate a short-lived Brain bearer token.",
    )
    parser.add_argument(
        "--chat-timeout",
        type=int,
        default=int(os.getenv("AT0_MVP_SMOKE_CHAT_TIMEOUT", "150")),
        help="Seconds to wait for each chat internet metadata frame.",
    )
    parser.add_argument(
        "--keep-chat-threads",
        action="store_true",
        default=os.getenv("AT0_MVP_SMOKE_KEEP_CHAT_THREADS", "").lower()
        in {"1", "true", "yes"},
        help="Keep chat threads created by this smoke for manual inspection.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    token = _smoke_token(
        explicit_token=args.token,
        profile=args.profile,
        base_url=base_url,
        token_ssh_target=args.token_ssh_target,
    )

    results: dict[str, SmokeResult] = {}
    created_thread_ids: list[str] = []
    for case in CHAT_CASES:
        result, thread_id = _chat_metadata_check(
            base_url=base_url,
            token=token,
            case=case,
            timeout=args.chat_timeout,
        )
        results[case.name] = result
        if thread_id:
            created_thread_ids.append(thread_id)

    results["browser_approval_visible_in_operator_queue"] = (
        _browser_approval_visible_check(base_url=base_url, token=token)
    )

    if created_thread_ids and not args.keep_chat_threads:
        for thread_id in dict.fromkeys(created_thread_ids):
            try:
                _archive_thread(base_url=base_url, token=token, thread_id=thread_id)
            except Exception as exc:
                print(
                    f"warning: failed to archive smoke chat thread {thread_id}: {exc}",
                    file=sys.stderr,
                )

    failures = [name for name, result in results.items() if result.status != "passed"]
    status = "passed" if not failures else "failed"
    _emit(
        {
            "status": status,
            "checks": {name: asdict(result) for name, result in results.items()},
        }
    )
    return 0 if status == "passed" else 2


def _chat_metadata_check(
    *,
    base_url: str,
    token: str,
    case: ChatSmokeCase,
    timeout: int,
) -> tuple[SmokeResult, str | None]:
    body = {
        "messages": [{"role": "user", "content": case.prompt}],
        "model": "auto",
        "stream": True,
        "internet_mode": case.internet_mode,
    }
    try:
        payloads = _call_sse_until(
            base_url=base_url,
            path="/v1/chat/completions",
            token=token,
            body=body,
            done=lambda seen: _metadata_for_mode(seen, case.internet_mode) is not None,
            timeout=timeout,
        )
    except Exception as exc:
        return SmokeResult("failed", {"error": _safe_error(exc)}), None

    metadata = _metadata_for_mode(payloads, case.internet_mode)
    if metadata is None:
        return (
            SmokeResult(
                "failed",
                {
                    "internet_mode": case.internet_mode,
                    "error": "chat stream did not return Beacon metadata",
                    "payload_count": len(payloads),
                },
            ),
            None,
        )

    summary = _chat_metadata_summary(metadata)
    checks = _chat_metadata_checks(metadata, case)
    failures = [name for name, passed in checks.items() if not passed]
    summary["checks"] = checks
    summary["failures"] = failures
    status = "passed" if not failures else "failed"
    return SmokeResult(status, summary), _optional_string(metadata.get("thread_id"))


def _chat_metadata_checks(
    metadata: dict[str, object],
    case: ChatSmokeCase,
) -> dict[str, bool]:
    citation_count = _int_value(metadata.get("internet_citation_count"))
    accepted_citations = _int_value(metadata.get("internet_accepted_citation_count"))
    citations = _citations(metadata)
    haystack = _citation_haystack(citations)
    return {
        "request_id_present": bool(
            _optional_string(metadata.get("internet_request_id"))
        ),
        "mode_used": metadata.get("internet_mode") == case.internet_mode,
        "search_tool_used": metadata.get("internet_selected_tool") == "search",
        "citation_present": (
            max(citation_count, accepted_citations, len(citations))
            >= case.min_citations
        ),
        "expected_host_present": (
            not case.expected_any_hosts
            or any(host.lower() in haystack for host in case.expected_any_hosts)
        ),
        "raw_web_content_untrusted": (
            metadata.get("raw_web_content_is_untrusted") is True
        ),
        "synthesis_requires_citations": (
            not case.require_synthesis_citations
            or metadata.get("internet_synthesis_required_behavior")
            == "answer_with_citations"
        ),
        "memory_auto_write_blocked": (
            metadata.get("internet_automatic_memory_write_allowed") is False
            and metadata.get("internet_memory_promotion_review_required") is True
        ),
        "planned_query_count": (
            _int_value(metadata.get("internet_research_report_planned_query_count"))
            >= case.min_planned_query_count
        ),
        "independent_source_count": (
            _int_value(
                metadata.get("internet_research_report_independent_source_count")
            )
            >= case.min_independent_source_count
        ),
    }


def _chat_metadata_summary(metadata: dict[str, object]) -> dict[str, object]:
    citations = _citations(metadata)
    first_citation = citations[0] if citations else {}
    return {
        "thread_id": metadata.get("thread_id"),
        "internet_request_id": metadata.get("internet_request_id"),
        "internet_mode": metadata.get("internet_mode"),
        "selected_tool": metadata.get("internet_selected_tool"),
        "citation_count": metadata.get("internet_citation_count"),
        "accepted_citation_count": metadata.get("internet_accepted_citation_count"),
        "source_quality_status": metadata.get("internet_source_quality_status"),
        "raw_web_content_is_untrusted": metadata.get("raw_web_content_is_untrusted"),
        "synthesis_answerable": metadata.get("internet_synthesis_answerable"),
        "synthesis_status": metadata.get("internet_synthesis_status"),
        "synthesis_required_behavior": metadata.get(
            "internet_synthesis_required_behavior"
        ),
        "research_planned_query_count": metadata.get(
            "internet_research_report_planned_query_count"
        ),
        "research_independent_source_count": metadata.get(
            "internet_research_report_independent_source_count"
        ),
        "first_citation_host": first_citation.get("host"),
    }


def _metadata_for_mode(
    payloads: list[dict[str, object]],
    internet_mode: str,
) -> dict[str, object] | None:
    for payload in reversed(payloads):
        if payload.get("internet_mode") == internet_mode:
            return payload
    return None


def _browser_approval_visible_check(*, base_url: str, token: str) -> SmokeResult:
    try:
        approval = _request_browser_approval(base_url=base_url, token=token)
        pending = _call_json(
            "GET",
            base_url,
            "/v1/approvals/pending",
            token,
            body=None,
            timeout=45,
        )
    except Exception as exc:
        return SmokeResult("failed", {"error": _safe_error(exc)})

    summary = _browser_visibility_summary(approval=approval, pending=pending)
    checks = _browser_visibility_checks(summary)
    failures = [name for name, passed in checks.items() if not passed]
    summary["checks"] = checks
    summary["failures"] = failures
    return SmokeResult("passed" if not failures else "failed", summary)


def _request_browser_approval(*, base_url: str, token: str) -> dict[str, Any]:
    return _call_json(
        "POST",
        base_url,
        "/v1/internet-scout/browser-task/approval-request",
        token,
        {
            "query": "Open https://example.com and report the page title",
            "requester": "at0_mvp_user_path.browser_approval",
            "tool_hint": "browser_use",
            "needs_interaction": True,
        },
        timeout=45,
    )


def _browser_visibility_summary(
    *,
    approval: dict[str, Any],
    pending: dict[str, Any],
) -> dict[str, Any]:
    approval_queue_id = _optional_string(approval.get("approval_queue_id"))
    visible_item = _find_pending_approval(pending, approval_queue_id)
    plan = approval.get("plan") if isinstance(approval.get("plan"), dict) else {}
    decision = plan.get("decision") if isinstance(plan.get("decision"), dict) else {}
    action_class = (
        visible_item.get("action_class")
        if isinstance(visible_item, dict)
        and isinstance(visible_item.get("action_class"), list)
        else []
    )
    return {
        "request_id": approval.get("request_id"),
        "approval_queue_id": approval_queue_id,
        "approval_status": approval.get("approval_status"),
        "selected_tool": decision.get("tool") or plan.get("selected_tool"),
        "requires_approval": decision.get("requires_approval"),
        "risk_tier": decision.get("tier") or visible_item.get("risk_tier")
        if isinstance(visible_item, dict)
        else decision.get("tier"),
        "pending_count": pending.get("count"),
        "visible_in_pending_queue": visible_item is not None,
        "pending_action_class": action_class,
        "pending_status": visible_item.get("status")
        if isinstance(visible_item, dict)
        else None,
        "pending_description": visible_item.get("description")
        if isinstance(visible_item, dict)
        else None,
    }


def _browser_visibility_checks(summary: dict[str, Any]) -> dict[str, bool]:
    action_class = summary.get("pending_action_class")
    if not isinstance(action_class, list):
        action_class = []
    return {
        "request_id_present": bool(_optional_string(summary.get("request_id"))),
        "approval_queue_id_present": bool(
            _optional_string(summary.get("approval_queue_id"))
        ),
        "approval_pending": summary.get("approval_status") == "pending",
        "browser_use_selected": summary.get("selected_tool") == "browser_use",
        "requires_human_approval": summary.get("requires_approval") is True,
        "risk_tier_t4": summary.get("risk_tier") == "T4",
        "visible_in_pending_queue": summary.get("visible_in_pending_queue") is True,
        "pending_status_visible": summary.get("pending_status") == "pending",
        "beacon_action_class_visible": "beacon_browser_use" in action_class,
    }


def _find_pending_approval(
    pending: dict[str, Any],
    approval_queue_id: str | None,
) -> dict[str, Any] | None:
    if not approval_queue_id:
        return None
    items = pending.get("pending")
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and str(item.get("id")) == approval_queue_id:
            return item
    return None


def _call_sse_until(
    *,
    base_url: str,
    path: str,
    token: str,
    body: dict[str, object],
    done: Callable[[list[dict[str, object]]], bool],
    timeout: int,
) -> list[dict[str, object]]:
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "Connection": "close",
        },
    )
    payloads: list[dict[str, object]] = []
    frame_lines: list[str] = []
    deadline = time.monotonic() + timeout
    try:
        with urllib.request.urlopen(
            request,
            context=ssl._create_unverified_context(),
            timeout=timeout,
        ) as response:
            for raw_line in response:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"timed out waiting for SSE frame from {path}")
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if line:
                    frame_lines.append(line)
                    continue
                payloads.extend(_parse_sse_frame(frame_lines))
                frame_lines = []
                if done(payloads):
                    return payloads
            if frame_lines:
                payloads.extend(_parse_sse_frame(frame_lines))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"POST {path} failed: HTTP {exc.code} {detail}") from exc
    return payloads


def _parse_sse_frame(lines: list[str]) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("data:"):
            continue
        data = stripped.removeprefix("data:").strip()
        if not data or data == "[DONE]":
            continue
        decoded = json.loads(data)
        if isinstance(decoded, dict):
            payloads.append(decoded)
    return payloads


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


def _archive_thread(*, base_url: str, token: str, thread_id: str) -> None:
    request = urllib.request.Request(
        f"{base_url}/v1/threads/{thread_id}",
        method="DELETE",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(
        request,
        context=ssl._create_unverified_context(),
        timeout=30,
    ):
        return


def _smoke_token(
    *,
    explicit_token: str | None,
    profile: str,
    base_url: str,
    token_ssh_target: str | None,
) -> str:
    if explicit_token:
        return explicit_token
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
        if generated:
            return generated
    raise RuntimeError("set AT0_MVP_SMOKE_TOKEN or AT0_MVP_SMOKE_TOKEN_SSH_TARGET")


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


def _citations(metadata: dict[str, object]) -> list[dict[str, object]]:
    citations = metadata.get("citations")
    if not isinstance(citations, list):
        return []
    return [item for item in citations if isinstance(item, dict)]


def _citation_haystack(citations: list[dict[str, object]]) -> str:
    values: list[str] = []
    for citation in citations:
        for key in ("host", "source_url", "url", "title"):
            value = citation.get(key)
            if isinstance(value, str):
                values.append(value)
    return " ".join(values).lower()


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _int_value(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _is_local_base_url(base_url: str) -> bool:
    return (
        "://localhost" in base_url
        or "://127.0.0.1" in base_url
        or "://[::1]" in base_url
    )


def _safe_error(exc: BaseException) -> str:
    return str(exc).replace("\n", " ")[:800]


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
