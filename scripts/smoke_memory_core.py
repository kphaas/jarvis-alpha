#!/usr/bin/env python3
"""Live smoke the Memory core paths without printing secrets or raw facts.

Checks:
- /memory chat command saves explicit semantic memory without model routing.
- Health saves enter the high-visibility review lane and create a Buddy event.
- Dream/Buddy consolidation scans synthetic working memory and queues T5 review.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import shlex
import socket
import ssl
import subprocess
import sys
from typing import Any
from uuid import uuid4
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "https://jarvis-brain.tail40ed36.ts.net:8186"
DEFAULT_SSH_TARGET = "jarvisbrain@jarvis-brain.tail40ed36.ts.net"
DEFAULT_PROFILE = "ken"
DEFAULT_PSQL = "/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql"


@dataclass(frozen=True)
class SmokeResult:
    status: str
    detail: dict[str, Any]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("MEMORY_CORE_SMOKE_BASE_URL", DEFAULT_BASE_URL),
        help="Alpha Brain base URL to probe.",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("MEMORY_CORE_SMOKE_PROFILE", DEFAULT_PROFILE),
        help="Profile passed to scripts/gen_test_token.py.",
    )
    parser.add_argument(
        "--token",
        default=(
            os.getenv("MEMORY_CORE_SMOKE_TOKEN")
            or os.getenv("HELM_ASK_SMOKE_TOKEN")
            or os.getenv("BEACON_SMOKE_TOKEN")
        ),
        help="Optional pre-generated bearer token.",
    )
    parser.add_argument(
        "--token-ssh-target",
        default=os.getenv("MEMORY_CORE_SMOKE_TOKEN_SSH_TARGET", DEFAULT_SSH_TARGET),
        help="SSH target used to generate a short-lived bearer token.",
    )
    parser.add_argument(
        "--db-ssh-target",
        default=os.getenv("MEMORY_CORE_SMOKE_DB_SSH_TARGET", DEFAULT_SSH_TARGET),
        help="SSH target for Brain psql setup/cleanup. Use 'none' for local.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.getenv("MEMORY_CORE_SMOKE_TIMEOUT", "90")),
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--keep-chat-thread",
        action="store_true",
        default=os.getenv("MEMORY_CORE_SMOKE_KEEP_CHAT_THREAD", "").lower()
        in {"1", "true", "yes"},
        help="Keep the synthetic /memory chat thread for manual inspection.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    db_ssh_target = _db_ssh_target(base_url, args.db_ssh_target)
    token = _smoke_token(
        explicit_token=args.token,
        profile=args.profile,
        base_url=base_url,
        token_ssh_target=args.token_ssh_target,
    )
    smoke_id = uuid4().hex

    user_id: str | None = None
    created_thread_ids: list[str] = []
    semantic_memory_ids: list[str] = []
    results: dict[str, SmokeResult] = {}

    try:
        summary = _call_json(
            "GET",
            base_url,
            "/v1/memory/summary?semantic_limit=1&working_limit=1",
            token,
            None,
            timeout=args.timeout,
        )
        user_id = _optional_string(summary.get("user_id"))
        if not user_id:
            raise RuntimeError("memory summary did not return user_id")

        _run_psql(_cleanup_sql(user_id=user_id, smoke_id=smoke_id), db_ssh_target)

        explicit_result, thread_id, explicit_memory_id = _explicit_memory_check(
            base_url=base_url,
            token=token,
            smoke_id=smoke_id,
            timeout=args.timeout,
        )
        results["slash_memory_explicit_save"] = explicit_result
        if thread_id:
            created_thread_ids.append(thread_id)
        if explicit_memory_id:
            semantic_memory_ids.append(explicit_memory_id)

        health_result, health_memory_id = _health_review_lane_check(
            base_url=base_url,
            token=token,
            smoke_id=smoke_id,
            timeout=args.timeout,
        )
        results["health_review_lane"] = health_result
        if health_memory_id:
            semantic_memory_ids.append(health_memory_id)

        dream_memory_id = _seed_dream_candidate(
            user_id=user_id,
            smoke_id=smoke_id,
            db_ssh_target=db_ssh_target,
        )
        results["dream_candidate_seeded"] = SmokeResult(
            "passed" if dream_memory_id else "failed",
            {"memory_id": _short_id(dream_memory_id)},
        )

        dream_scan = _dream_proposals_check(
            base_url=base_url,
            token=token,
            dry_run=True,
            timeout=args.timeout,
        )
        results["dream_candidate_scan"] = dream_scan

        dream_queue = _dream_proposals_check(
            base_url=base_url,
            token=token,
            dry_run=False,
            timeout=args.timeout,
        )
        results["dream_t5_queue"] = dream_queue
    except Exception as exc:
        results.setdefault(
            "runtime", SmokeResult("failed", {"error": _safe_error(exc)})
        )
    finally:
        for memory_id in semantic_memory_ids:
            try:
                _review_memory(
                    base_url=base_url,
                    token=token,
                    memory_id=memory_id,
                    action="archive",
                    timeout=args.timeout,
                )
            except Exception as exc:
                results[f"cleanup_semantic_{_short_id(memory_id)}"] = SmokeResult(
                    "failed",
                    {"error": _safe_error(exc)},
                )

        if not args.keep_chat_thread:
            for thread_id in dict.fromkeys(created_thread_ids):
                try:
                    _archive_thread(base_url=base_url, token=token, thread_id=thread_id)
                except Exception as exc:
                    results[f"cleanup_thread_{_short_id(thread_id)}"] = SmokeResult(
                        "failed",
                        {"error": _safe_error(exc)},
                    )

        if user_id:
            try:
                cleanup_output = _run_psql(
                    _cleanup_sql(user_id=user_id, smoke_id=smoke_id),
                    db_ssh_target,
                )
                results["cleanup"] = SmokeResult(
                    "passed",
                    _json_object_or_text(cleanup_output),
                )
            except Exception as exc:
                results["cleanup"] = SmokeResult(
                    "failed",
                    {"error": _safe_error(exc)},
                )

    failures = [name for name, result in results.items() if result.status != "passed"]
    status = "passed" if not failures else "failed"
    _emit(
        {
            "status": status,
            "smoke_id": smoke_id,
            "checks": {name: asdict(result) for name, result in results.items()},
        }
    )
    return 0 if status == "passed" else 2


def _explicit_memory_check(
    *,
    base_url: str,
    token: str,
    smoke_id: str,
    timeout: int,
) -> tuple[SmokeResult, str | None, str | None]:
    fact = f"Memory core smoke preference marker {smoke_id}"
    payloads = _call_sse(
        base_url=base_url,
        path="/v1/chat/completions",
        token=token,
        body={
            "messages": [{"role": "user", "content": f"/memory preference {fact}"}],
            "model": "auto",
            "stream": True,
            "internet_mode": "none",
        },
        timeout=timeout,
    )
    response_text = "".join(
        str(payload.get("delta") or "")
        for payload in payloads
        if isinstance(payload, dict)
    )
    thread_id = _last_string_payload(payloads, "thread_id")

    summary = _call_json(
        "GET",
        base_url,
        "/v1/memory/summary?semantic_limit=50&working_limit=1",
        token,
        None,
        timeout=timeout,
    )
    item = _find_semantic_memory(summary, fact)
    telemetry = _call_json(
        "GET",
        base_url,
        "/v1/memory/telemetry?recent_limit=20",
        token,
        None,
        timeout=timeout,
    )
    checks = _explicit_memory_checks(
        response_text=response_text,
        item=item,
        telemetry=telemetry,
    )
    failures = [name for name, passed in checks.items() if not passed]
    detail = {
        "thread_id": _short_id(thread_id),
        "memory_id": _short_id(item.get("id") if item else None),
        "source_surface": _nested_string(item, "provenance", "source_surface"),
        "source_action": _nested_string(item, "provenance", "source_action"),
        "checks": checks,
        "failures": failures,
    }
    return (
        SmokeResult("passed" if not failures else "failed", detail),
        thread_id,
        _optional_string(item.get("id")) if item else None,
    )


def _explicit_memory_checks(
    *,
    response_text: str,
    item: dict[str, Any] | None,
    telemetry: dict[str, Any],
) -> dict[str, bool]:
    memory_id = _optional_string(item.get("id")) if item else None
    return {
        "deterministic_response": response_text.strip()
        == "Saved to semantic memory as preference.",
        "summary_visible": item is not None,
        "category_preference": item is not None
        and item.get("category") == "preference",
        "source_surface_at0_chat": _nested_string(item, "provenance", "source_surface")
        == "at0_chat",
        "source_action_slash_command": _nested_string(
            item,
            "provenance",
            "source_action",
        )
        == "slash_memory_command",
        "telemetry_has_metadata_only_event": _telemetry_has_semantic_event(
            telemetry,
            memory_id=memory_id,
            source_surface="at0_chat",
            source_action="slash_memory_command",
        ),
    }


def _health_review_lane_check(
    *,
    base_url: str,
    token: str,
    smoke_id: str,
    timeout: int,
) -> tuple[SmokeResult, str | None]:
    fact = f"Memory core smoke health review marker {smoke_id}"
    saved = _call_json(
        "POST",
        base_url,
        "/v1/memory/semantic",
        token,
        {
            "fact": fact,
            "category": "health",
            "source_surface": "memory_core_smoke",
            "source_action": "health_review_lane_probe",
        },
        timeout=timeout,
    )
    result = saved.get("result") if isinstance(saved.get("result"), dict) else {}
    telemetry = _call_json(
        "GET",
        base_url,
        "/v1/memory/telemetry?recent_limit=20",
        token,
        None,
        timeout=timeout,
    )
    checks = _health_review_lane_checks(result=result, telemetry=telemetry)
    failures = [name for name, passed in checks.items() if not passed]
    detail = {
        "memory_id": _short_id(result.get("id")),
        "buddy_event_id": _short_id(result.get("buddy_event_id")),
        "review_status": result.get("review_status"),
        "review_reason": result.get("review_reason"),
        "checks": checks,
        "failures": failures,
    }
    return (
        SmokeResult("passed" if not failures else "failed", detail),
        _optional_string(result.get("id")),
    )


def _health_review_lane_checks(
    *,
    result: dict[str, Any],
    telemetry: dict[str, Any],
) -> dict[str, bool]:
    memory_id = _optional_string(result.get("id"))
    return {
        "saved": result.get("saved") is True,
        "review_required": result.get("review_required") is True,
        "pending_review": result.get("review_status") == "pending_review",
        "sensitive_reason": result.get("review_reason") == "sensitive_category",
        "buddy_event_created": bool(_optional_string(result.get("buddy_event_id"))),
        "telemetry_has_review_event": _telemetry_has_semantic_event(
            telemetry,
            memory_id=memory_id,
            source_surface="memory_core_smoke",
            source_action="health_review_lane_probe",
        ),
    }


def _seed_dream_candidate(
    *,
    user_id: str,
    smoke_id: str,
    db_ssh_target: str | None,
) -> str | None:
    output = _run_psql(
        _seed_dream_candidate_sql(user_id=user_id, smoke_id=smoke_id), db_ssh_target
    )
    return _optional_string(output.strip())


def _dream_proposals_check(
    *,
    base_url: str,
    token: str,
    dry_run: bool,
    timeout: int,
) -> SmokeResult:
    response = _call_json(
        "POST",
        base_url,
        "/v1/memory/consolidation/proposals",
        token,
        {
            "dry_run": dry_run,
            "semantic_limit": 200,
            "conversation_limit": 200,
        },
        timeout=timeout,
    )
    checks = _dream_proposal_checks(response=response, dry_run=dry_run)
    failures = [name for name, passed in checks.items() if not passed]
    proposals = [
        item for item in response.get("proposals", []) if isinstance(item, dict)
    ]
    executable = [item for item in proposals if item.get("executable") is True]
    detail = {
        "status": response.get("status"),
        "candidate_count": response.get("candidate_count"),
        "executable_count": response.get("executable_count"),
        "informational_count": response.get("informational_count"),
        "queued_proposals": len(
            [
                item
                for item in executable
                if _optional_string(item.get("proposal_id"))
                and _optional_string(item.get("approval_queue_id"))
            ]
        ),
        "actions": sorted(
            {
                str(item.get("proposed_action"))
                for item in proposals
                if item.get("proposed_action")
            }
        ),
        "checks": checks,
        "failures": failures,
    }
    return SmokeResult("passed" if not failures else "failed", detail)


def _dream_proposal_checks(
    *,
    response: dict[str, Any],
    dry_run: bool,
) -> dict[str, bool]:
    proposals = [
        item for item in response.get("proposals", []) if isinstance(item, dict)
    ]
    executable = [item for item in proposals if item.get("executable") is True]
    promoted = [
        item
        for item in executable
        if item.get("proposed_action") == "promote_episodic_to_semantic"
    ]
    return {
        "status_matches_mode": response.get("status")
        == ("dry_run" if dry_run else "queued"),
        "review_ready_or_clear": response.get("report_status")
        in {"review_ready", "clear"},
        "candidate_found": int(response.get("candidate_count") or 0) >= 1,
        "executable_found": int(response.get("executable_count") or 0) >= 1,
        "promotion_candidate_present": bool(promoted),
        "writes_still_review_gated": response.get("write_actions_enabled") is False,
        "dry_run_has_no_queue_ids": (
            not dry_run
            or all(
                item.get("proposal_id") is None
                and item.get("approval_queue_id") is None
                for item in proposals
            )
        ),
        "queued_has_proposal_and_approval_ids": (
            dry_run
            or any(
                _optional_string(item.get("proposal_id"))
                and _optional_string(item.get("approval_queue_id"))
                and item.get("status") == "queued"
                for item in promoted
            )
        ),
    }


def _find_semantic_memory(
    summary: dict[str, Any],
    fact: str,
) -> dict[str, Any] | None:
    semantic = summary.get("semantic")
    if not isinstance(semantic, list):
        return None
    for item in semantic:
        if isinstance(item, dict) and item.get("fact") == fact:
            return item
    return None


def _telemetry_has_semantic_event(
    telemetry: dict[str, Any],
    *,
    memory_id: str | None,
    source_surface: str,
    source_action: str,
) -> bool:
    if not memory_id:
        return False
    events = telemetry.get("recent_semantic_saves")
    if not isinstance(events, list):
        return False
    for event in events:
        if not isinstance(event, dict):
            continue
        if (
            event.get("id") == memory_id
            and event.get("source_surface") == source_surface
            and event.get("source_action") == source_action
            and "fact" not in event
        ):
            return True
    return False


def _call_sse(
    *,
    base_url: str,
    path: str,
    token: str,
    body: dict[str, object],
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
    try:
        with urllib.request.urlopen(
            request,
            context=ssl._create_unverified_context(),
            timeout=timeout,
        ) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if line:
                    frame_lines.append(line)
                    continue
                payloads.extend(_parse_sse_frame(frame_lines))
                frame_lines = []
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


def _review_memory(
    *,
    base_url: str,
    token: str,
    memory_id: str,
    action: str,
    timeout: int,
) -> None:
    _call_json(
        "POST",
        base_url,
        f"/v1/memory/semantic/{memory_id}/review",
        token,
        {"action": action, "note": "memory core smoke cleanup"},
        timeout=timeout,
    )


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


def _seed_dream_candidate_sql(*, user_id: str, smoke_id: str) -> str:
    session_id = f"memory_core_smoke_{smoke_id}"
    summary = f"Memory core smoke Dream promotion candidate {smoke_id}"
    return f"""
SELECT public.store_conversation_memory(
  '{user_id}',
  '{session_id}',
  'user',
  '{summary}',
  array_fill(0.1, ARRAY[768])::vector,
  'working',
  false,
  0.95
)::text;
"""


def _cleanup_sql(*, user_id: str, smoke_id: str) -> str:
    session_id = f"memory_core_smoke_{smoke_id}"
    return f"""
WITH smoke_conversation AS (
    SELECT id::text
      FROM public.alpha_conversation_memory
     WHERE user_id = '{user_id}'
       AND (
            session_id = '{session_id}'
            OR summary ILIKE '%{smoke_id}%'
            OR content ILIKE '%{smoke_id}%'
       )
),
smoke_semantic AS (
    SELECT id::text
      FROM public.alpha_semantic_memory
     WHERE user_id = '{user_id}'::uuid
       AND fact ILIKE '%{smoke_id}%'
),
smoke_proposals AS (
    SELECT p.id, p.approval_queue_id
      FROM public.alpha_memory_consolidation_proposals AS p
     WHERE p.user_id = '{user_id}'::uuid
       AND (
            p.evidence->>'summary' ILIKE '%{smoke_id}%'
            OR p.evidence->>'memory_id' IN (SELECT id FROM smoke_conversation)
            OR p.source_memory_ids && ARRAY(SELECT id FROM smoke_conversation)
       )
),
approval_ids AS (
    SELECT approval_queue_id AS id
      FROM smoke_proposals
     WHERE approval_queue_id IS NOT NULL
),
deleted_ledger AS (
    DELETE FROM public.alpha_memory_consolidation_execution_ledger AS ledger
     WHERE ledger.proposal_id IN (SELECT id FROM smoke_proposals)
     RETURNING 1
),
deleted_proposals AS (
    DELETE FROM public.alpha_memory_consolidation_proposals AS p
     WHERE p.id IN (SELECT id FROM smoke_proposals)
     RETURNING 1
),
deleted_approval_audit AS (
    DELETE FROM public.alpha_approval_audit AS audit
     WHERE audit.approval_id IN (SELECT id FROM approval_ids)
     RETURNING 1
),
deleted_approval_queue AS (
    DELETE FROM public.alpha_approval_queue AS queue
     WHERE queue.id IN (SELECT id FROM approval_ids)
     RETURNING 1
),
deleted_buddy AS (
    DELETE FROM public.alpha_buddy_events AS event
     WHERE event.user_id = '{user_id}'
       AND (
            event.source = 'memory_core_smoke'
            OR (
                event.source = 'semantic_memory_review'
                AND (
                    event.payload->>'source_surface' = 'memory_core_smoke'
                    OR event.payload->>'memory_id' IN (SELECT id FROM smoke_semantic)
                )
            )
       )
     RETURNING 1
),
deleted_semantic AS (
    DELETE FROM public.alpha_semantic_memory AS memory
     WHERE memory.id::text IN (SELECT id FROM smoke_semantic)
     RETURNING 1
),
deleted_conversation AS (
    DELETE FROM public.alpha_conversation_memory AS memory
     WHERE memory.id::text IN (SELECT id FROM smoke_conversation)
     RETURNING 1
)
SELECT json_build_object(
    'ledger', (SELECT COUNT(*) FROM deleted_ledger),
    'proposals', (SELECT COUNT(*) FROM deleted_proposals),
    'approval_audit', (SELECT COUNT(*) FROM deleted_approval_audit),
    'approval_queue', (SELECT COUNT(*) FROM deleted_approval_queue),
    'buddy_events', (SELECT COUNT(*) FROM deleted_buddy),
    'semantic', (SELECT COUNT(*) FROM deleted_semantic),
    'conversation', (SELECT COUNT(*) FROM deleted_conversation)
)::text;
"""


def _run_psql(sql: str, ssh_target: str | None) -> str:
    shell_script = f"""
set -euo pipefail
PSQL="${{PSQL:-{DEFAULT_PSQL}}}"
DB="${{DB:-jarvis_alpha}}"
OWNER_ROLE="${{OWNER_ROLE:-jarvisbrain}}"
if [[ -f "${{HOME}}/jarvis/.secrets" ]]; then
  SECRETS_FILE="${{HOME}}/jarvis/.secrets"
elif [[ -f "${{HOME}}/.secrets" ]]; then
  SECRETS_FILE="${{HOME}}/.secrets"
else
  echo "secrets file not found" >&2
  exit 1
fi
set -a
source "$SECRETS_FILE"
set +a
PGPASSWORD="$POSTGRES_PASSWORD" "$PSQL" -h localhost -U "$OWNER_ROLE" -d "$DB" -v ON_ERROR_STOP=1 -tAc {shlex.quote(sql)}
"""
    if ssh_target:
        return subprocess.check_output(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "StrictHostKeyChecking=no",
                ssh_target,
                "bash -se",
            ],
            input=shell_script,
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    return subprocess.check_output(
        ["bash", "-se"],
        input=shell_script,
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


def _smoke_token(
    *,
    explicit_token: str | None,
    profile: str,
    base_url: str,
    token_ssh_target: str | None,
) -> str:
    if explicit_token:
        return explicit_token
    if _is_local_base_url(base_url) or _running_on_brain():
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
    raise RuntimeError(
        "set MEMORY_CORE_SMOKE_TOKEN or MEMORY_CORE_SMOKE_TOKEN_SSH_TARGET"
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


def _db_ssh_target(base_url: str, target: str | None) -> str | None:
    if _is_local_base_url(base_url) or _running_on_brain():
        return None
    if not target:
        return None
    clean = target.strip()
    return None if clean.lower() in {"", "none", "null", "off", "false", "0"} else clean


def _running_on_brain() -> bool:
    hostname = socket.gethostname().split(".", 1)[0]
    return hostname == "jarvis-brain"


def _is_local_base_url(base_url: str) -> bool:
    return (
        "://localhost" in base_url
        or "://127.0.0.1" in base_url
        or "://[::1]" in base_url
    )


def _last_string_payload(payloads: list[dict[str, object]], key: str) -> str | None:
    for payload in reversed(payloads):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _nested_string(
    item: dict[str, Any] | None,
    parent_key: str,
    child_key: str,
) -> str | None:
    if not item:
        return None
    parent = item.get(parent_key)
    if not isinstance(parent, dict):
        return None
    return _optional_string(parent.get(child_key))


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _short_id(value: object) -> str | None:
    text = _optional_string(value)
    if not text:
        return None
    return text[:8]


def _safe_error(exc: BaseException) -> str:
    return str(exc).replace("\n", " ")[:800]


def _json_object_or_text(value: str) -> dict[str, Any]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {"output": value[:200]}
    return payload if isinstance(payload, dict) else {"output": value[:200]}


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
