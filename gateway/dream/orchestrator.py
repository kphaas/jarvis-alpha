"""
Dream Mode Orchestrator — runs on Gateway, drives overnight sessions.

Usage:
    python3 -m gateway.dream.orchestrator --session-file /path/to/session.json
    python3 -m gateway.dream.orchestrator --dry-run --session-file /path/to/session.json

Session file format:
{
    "steps": [
        {"step_index": 0, "name": "canary", "agent_type": "canary"},
        {"step_index": 1, "name": "task_name", "agent_type": "llm", "depends_on": [0]}
    ],
    "cost_budget_usd": 5.0,
    "max_duration_s": 14400
}
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Use curl + asyncio.to_thread for all HTTP (httpx fails with Tailscale TLS)


# ── Configuration ──────────────────────────────────────────────

BRAIN_URL = None  # Set from env JARVIS_ALPHA_BRAIN_URL or secrets
ALPHA_SERVICE_TOKEN = None  # Set from env or secrets
MAX_CALLS_PER_SESSION = 200  # Circuit breaker
POLL_INTERVAL_S = 2  # Seconds between next-step polls
RETRY_BACKOFF = [5, 15, 45]  # Seconds between retries


def _load_config():
    """Load Brain URL and Gateway token from environment or secrets file."""
    global BRAIN_URL, ALPHA_SERVICE_TOKEN
    import os

    BRAIN_URL = os.environ.get("JARVIS_ALPHA_BRAIN_URL")
    ALPHA_SERVICE_TOKEN = os.environ.get("ALPHA_SERVICE_TOKEN")

    if not BRAIN_URL or not ALPHA_SERVICE_TOKEN:
        secrets_path = Path.home() / "jarvis" / ".secrets"
        if secrets_path.exists():
            for line in secrets_path.read_text().splitlines():
                line = line.strip()
                if "=" not in line or line.startswith("#"):
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key == "JARVIS_ALPHA_BRAIN_URL" and not BRAIN_URL:
                    BRAIN_URL = val
                elif key == "ALPHA_SERVICE_TOKEN" and not ALPHA_SERVICE_TOKEN:
                    ALPHA_SERVICE_TOKEN = val

    if not BRAIN_URL:
        print("FATAL: JARVIS_ALPHA_BRAIN_URL not set", file=sys.stderr)
        sys.exit(1)
    if not ALPHA_SERVICE_TOKEN:
        print("FATAL: ALPHA_SERVICE_TOKEN not set", file=sys.stderr)
        sys.exit(1)


# ── HTTP via curl (Tailscale TLS safe) ─────────────────────────

async def _curl(method: str, path: str, body: dict | None = None) -> dict:
    """Make an authenticated request to Brain via curl."""
    url = f"{BRAIN_URL}{path}"
    cmd = ["curl", "-sk", "-X", method, "-H", f"Authorization: Bearer {ALPHA_SERVICE_TOKEN}"]
    if body is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(body)]
    cmd.append(url)

    result = await asyncio.to_thread(
        subprocess.run, cmd, capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr}")
    if not result.stdout.strip():
        return {}
    return json.loads(result.stdout)


async def _curl_get(path: str) -> dict:
    return await _curl("GET", path)


async def _curl_post(path: str, body: dict | None = None) -> dict:
    return await _curl("POST", path, body)


async def _curl_patch(path: str, body: dict) -> dict:
    return await _curl("PATCH", path, body)


# ── Circuit Breaker ────────────────────────────────────────────

class CircuitBreaker:
    """Tracks total API/LLM calls per session. Trips at MAX_CALLS_PER_SESSION."""

    def __init__(self, max_calls: int = MAX_CALLS_PER_SESSION):
        self.max_calls = max_calls
        self.call_count = 0

    def increment(self):
        self.call_count += 1

    @property
    def tripped(self) -> bool:
        return self.call_count >= self.max_calls

    @property
    def remaining(self) -> int:
        return max(0, self.max_calls - self.call_count)


# ── Step Dispatchers ───────────────────────────────────────────

async def _dispatch_canary(step: dict, dry_run: bool) -> dict:
    """Step 0 health probe — checks Brain is alive."""
    if dry_run:
        return {"output_summary": "DRY_RUN: canary skipped", "verification": "dry_run", "cost_usd": 0}

    try:
        result = await _curl_get("/health")
        if result.get("status") == "ok":
            return {"output_summary": "Brain health OK", "verification": "health_check_passed", "cost_usd": 0}
        else:
            raise RuntimeError(f"Health check returned: {result}")
    except Exception as e:
        raise RuntimeError(f"Canary failed: {e}")


async def _dispatch_llm(step: dict, dry_run: bool) -> dict:
    """Local Ollama call via Brain."""
    if dry_run:
        return {"output_summary": f"DRY_RUN: would run LLM step '{step['name']}'", "verification": "dry_run", "cost_usd": 0}

    prompt = step.get("description") or f"Execute task: {step['name']}"
    result = await _curl_post("/v1/cloud/call", {
        "provider": "ollama",
        "payload": {
            "model": "llama3.1:8b",
            "messages": [{"role": "user", "content": prompt}]
        }
    })
    output = str(result.get("result", ""))[:500]
    return {
        "output_summary": output,
        "verification": "llm_response_received" if output else "empty_response",
        "cost_usd": 0,
        "model_used": "llama3.1:8b",
    }


async def _dispatch_cloud(step: dict, dry_run: bool) -> dict:
    """Cloud LLM call via Gateway adapter (Claude/Perplexity/Gemini)."""
    if dry_run:
        return {"output_summary": f"DRY_RUN: would run cloud step '{step['name']}'", "verification": "dry_run", "cost_usd": 0}

    prompt = step.get("description") or f"Execute task: {step['name']}"
    result = await _curl_post("/v1/cloud/call", {
        "provider": "claude",
        "payload": {
            "model": "claude-haiku-4-5-20251001",
            "system": "You are a task execution agent. Be concise.",
            "messages": [{"role": "user", "content": prompt}]
        }
    })
    output = str(result.get("result", ""))[:500]
    cost = float(result.get("cost_usd", 0.005))
    return {
        "output_summary": output,
        "verification": "cloud_response_received" if output else "empty_response",
        "cost_usd": cost,
        "model_used": "claude-haiku-4-5-20251001",
    }


async def _dispatch_tool(step: dict, dry_run: bool) -> dict:
    """Tool agent — stub for now."""
    if dry_run:
        return {"output_summary": f"DRY_RUN: would run tool step '{step['name']}'", "verification": "dry_run", "cost_usd": 0}
    return {"output_summary": "tool_agent not yet implemented", "verification": "stub", "cost_usd": 0}


DISPATCHERS = {
    "canary": _dispatch_canary,
    "llm": _dispatch_llm,
    "cloud": _dispatch_cloud,
    "tool": _dispatch_tool,
    "code": _dispatch_tool,  # alias until code agent is built
}


# ── Post-Action Verification ──────────────────────────────────

def _verify_output(result: dict, step: dict) -> bool:
    """Basic verification: output_summary must be non-empty and verification must be set."""
    summary = result.get("output_summary", "")
    verification = result.get("verification", "")
    if not summary or not verification:
        return False
    if verification in ("stub", "empty_response"):
        return False
    return True


# ── Main Orchestrator Loop ────────────────────────────────────

async def run_session(session_file: Path, dry_run: bool = False):
    """Main entry point: create session, execute steps, finalize."""
    _load_config()

    # Load session definition
    with open(session_file) as f:
        session_def = json.load(f)

    trigger = "dry_run" if dry_run else session_def.get("trigger", "manual")
    budget = session_def.get("cost_budget_usd", 5.0)
    max_duration = session_def.get("max_duration_s", 14400)

    # Create session on Brain
    create_resp = await _curl_post("/v1/dream/sessions", {
        "trigger": trigger,
        "cost_budget_usd": budget,
        "max_duration_s": max_duration,
        "steps": session_def["steps"],
    })
    session_id = create_resp["session_id"]
    print(f"[DREAM] Session {session_id} created ({trigger}, budget=${budget}, max={max_duration}s)")

    # Start session
    await _curl_post(f"/v1/dream/sessions/{session_id}/start")
    print(f"[DREAM] Session {session_id} started")

    breaker = CircuitBreaker()
    start_time = time.monotonic()

    # Execution loop
    while True:
        # Watchdog: wall-clock timeout
        elapsed = time.monotonic() - start_time
        if elapsed >= max_duration:
            print(f"[DREAM] Wall-clock timeout ({max_duration}s) — killing session")
            await _curl_post(f"/v1/dream/sessions/{session_id}/kill", {
                "reason": f"wall-clock timeout after {int(elapsed)}s"
            })
            break

        # Circuit breaker
        if breaker.tripped:
            print(f"[DREAM] Circuit breaker tripped ({breaker.call_count} calls) — killing session")
            await _curl_post(f"/v1/dream/sessions/{session_id}/kill", {
                "reason": f"circuit breaker: {breaker.call_count} calls exceeded limit"
            })
            break

        # Get next runnable step
        next_resp = await _curl_get(f"/v1/dream/sessions/{session_id}/next-step")
        step = next_resp.get("next_step")
        if not step:
            reason = next_resp.get("reason", "unknown")
            print(f"[DREAM] No more runnable steps: {reason}")
            break

        step_id = step["id"]
        step_name = step["name"]
        agent_type = step.get("agent_type", "llm")
        print(f"[DREAM] Running step {step['step_index']}: {step_name} ({agent_type})")

        # Mark step running
        await _curl_patch(f"/v1/dream/steps/{step_id}", {"status": "running"})

        # Dispatch
        dispatcher = DISPATCHERS.get(agent_type)
        if not dispatcher:
            await _curl_patch(f"/v1/dream/steps/{step_id}", {
                "status": "failed",
                "error_message": f"Unknown agent_type: {agent_type}",
            })
            continue

        retries = 0
        max_retries = step.get("max_retries", 3)
        success = False

        result = None
        while retries <= max_retries:
            try:
                breaker.increment()
                input_data = json.dumps({"name": step_name, "description": step.get("description")})
                input_hash = hashlib.sha256(input_data.encode()).hexdigest()[:16]

                result = await dispatcher(step, dry_run)
                result["input_hash"] = input_hash

                # Post-action verification
                if _verify_output(result, step):
                    result["status"] = "completed"
                    await _curl_patch(f"/v1/dream/steps/{step_id}", result)
                    print(f"[DREAM]   ✓ Step {step_name} completed (cost=${result.get('cost_usd', 0):.4f})")
                    success = True
                    break
                else:
                    raise RuntimeError(f"Verification failed: {result.get('verification', 'none')}")

            except Exception as e:
                retries += 1
                if retries > max_retries:
                    await _curl_patch(f"/v1/dream/steps/{step_id}", {
                        "status": "failed",
                        "error_message": str(e)[:500],
                        "cost_usd": result.get("cost_usd", 0) if result is not None else 0,
                    })
                    print(f"[DREAM]   ✗ Step {step_name} FAILED after {max_retries} retries: {e}")
                    break
                else:
                    backoff = RETRY_BACKOFF[min(retries - 1, len(RETRY_BACKOFF) - 1)]
                    print(f"[DREAM]   ↻ Retry {retries}/{max_retries} in {backoff}s: {e}")
                    await asyncio.sleep(backoff)

        await asyncio.sleep(POLL_INTERVAL_S)

    # Finalize session
    final = await _curl_post(f"/v1/dream/sessions/{session_id}/complete")
    print(f"[DREAM] Session {session_id} finished: {final.get('status')} — {final.get('summary')}")
    return final


# ── CLI Entry Point ───────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Dream Mode Orchestrator")
    parser.add_argument("--session-file", required=True, help="Path to session definition JSON")
    parser.add_argument("--dry-run", action="store_true", help="Simulate execution without real LLM calls")
    args = parser.parse_args()

    session_path = Path(args.session_file)
    if not session_path.exists():
        print(f"FATAL: Session file not found: {session_path}", file=sys.stderr)
        sys.exit(1)

    result = asyncio.run(run_session(session_path, dry_run=args.dry_run))
    sys.exit(0 if result.get("status") == "completed" else 1)


if __name__ == "__main__":
    main()
