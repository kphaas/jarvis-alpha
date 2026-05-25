#!/usr/bin/env bash
set -euo pipefail

cd "${JARVIS_ALPHA_HOME:-$HOME/jarvis-alpha}"
PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python3.12}"

exec "$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

from brain.config.node_addresses import BRAIN_URL

BASE = (
    os.environ.get("JARVIS_ALPHA_BRAIN_URL")
    or os.environ.get("ALPHA_BRAIN_URL")
    or BRAIN_URL
).rstrip("/")
PROFILE = os.environ.get("DREAM_SMOKE_PROFILE", "ken")
POLL_LIMIT = int(os.environ.get("DREAM_SMOKE_POLLS", "60"))
POLL_INTERVAL_S = float(os.environ.get("DREAM_SMOKE_POLL_INTERVAL_S", "5"))
EXECUTE_READONLY = os.environ.get("DREAM_SMOKE_EXECUTE_READONLY", "1") != "0"
TERMINAL = {"completed", "failed", "aborted", "killed", "halted"}
CTX = ssl._create_unverified_context()


def emit(value: dict) -> None:
    print(json.dumps(value, sort_keys=True), flush=True)


def token() -> str:
    return subprocess.check_output(
        [os.environ.get("PYTHON_BIN", ".venv/bin/python3.12"), "scripts/gen_test_token.py", PROFILE],
        text=True,
    ).strip()


TOKEN = token()


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        emit({"http_error": exc.code, "path": path, "body": error_body[:1200]})
        raise


payload = {
    "goal_type": "default",
    "goal_text": (
        "Dream smoke: create a concise read-only plan that verifies the Temporal "
        "planner, reviewer, run-id persistence, health checks, and read-only "
        "execution scaffold. The plan must not modify files, databases, services, "
        "secrets, LaunchAgents, networking, approvals, or production data."
    ),
    "prompt_version": "v1",
    "recent_context": "Canonical smoke script for Dream Temporal D3.5.",
    "prior_lessons": (
        "Keep this smoke read-only and minimal. Autonomous write execution remains "
        "disabled behind future approval gates."
    ),
    "trigger": "dry_run",
    "cost_budget_usd": 0.25,
    "max_duration_s": 600,
}

created = call("POST", "/v1/dream/sessions", payload)
session_id = created["session_id"]
emit({"created": created})
started = call("POST", f"/v1/dream/sessions/{session_id}/start")
emit({"started": started})

last = None
for attempt in range(1, POLL_LIMIT + 1):
    last = call("GET", f"/v1/dream/sessions/{session_id}")
    session = last["session"]
    status = session["status"]
    emit(
        {
            "poll": attempt,
            "session_id": session_id,
            "status": status,
            "workflow_id": session.get("temporal_workflow_id"),
            "run_id_set": bool(session.get("temporal_run_id")),
            "step_count": session.get("step_count"),
            "steps_returned": len(last.get("steps", [])),
            "review_verdict": session.get("review_verdict"),
        }
    )
    if status in TERMINAL:
        break
    time.sleep(POLL_INTERVAL_S)

if last is None:
    emit({"error": "no final response"})
    sys.exit(3)

session = last["session"]
if session.get("status") != "completed" or not session.get("temporal_run_id"):
    emit({"final": session, "error": "dream planning smoke failed"})
    sys.exit(2)

readonly = None
if EXECUTE_READONLY:
    readonly = call(
        "POST",
        f"/v1/dream/sessions/{session_id}/execute-readonly",
        {"limit": 20},
    )
    emit({"readonly": readonly})

health = call("GET", "/v1/dream/health")
emit({"health": health})
if health.get("status") != "ok":
    emit({"error": "dream health degraded"})
    sys.exit(4)

emit(
    {
        "final": {
            "session_id": session_id,
            "status": session.get("status"),
            "workflow_id": session.get("temporal_workflow_id"),
            "temporal_run_id": session.get("temporal_run_id"),
            "review_verdict": session.get("review_verdict"),
            "step_count": session.get("step_count"),
            "readonly_executed": len(readonly.get("executed", [])) if readonly else 0,
        }
    }
)
PY
