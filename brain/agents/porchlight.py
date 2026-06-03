"""Manual runner wrapper for the Porchlight security sweep."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import UUID

import asyncpg

from brain.agents.runtime import AgentRuntime, AgentRuntimeConfig

PORCHLIGHT_AGENT_ID = "porchlight"
DEFAULT_PORCHLIGHT_INTERVAL_SECONDS = 24 * 60 * 60
REPO_ROOT = Path(__file__).resolve().parents[2]
PORCHLIGHT_SCRIPT = REPO_ROOT / "scripts" / "porchlight_security_agent.py"


async def maybe_run_porchlight(pool: asyncpg.Pool) -> bool:
    runtime = AgentRuntime(
        AgentRuntimeConfig(
            agent_id=PORCHLIGHT_AGENT_ID,
            trigger_type="scheduled",
            source="buddy",
        ),
        pool=pool,
    )
    state = await runtime.load_state()
    if state is None:
        return False
    interval = int(
        state.metadata.get(
            "schedule_interval_seconds", DEFAULT_PORCHLIGHT_INTERVAL_SECONDS
        )
    )
    if not await runtime.claim_due(interval_seconds=interval):
        return False
    await runtime.run_once(_run_porchlight_script)
    return True


async def run_porchlight_now(pool: asyncpg.Pool):
    runtime = AgentRuntime(
        AgentRuntimeConfig(
            agent_id=PORCHLIGHT_AGENT_ID,
            trigger_type="manual",
            source="http",
        ),
        pool=pool,
    )
    return await runtime.run_once(_run_porchlight_script)


async def _run_porchlight_script(_run_id: UUID) -> dict:
    env = os.environ.copy()
    env.setdefault("SECRETS_FILE", str(Path.home() / "jarvis" / ".secrets"))
    env.setdefault("PYTHONPATH", f"{REPO_ROOT}:{REPO_ROOT / 'common'}")
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(PORCHLIGHT_SCRIPT),
        "--json",
        "--report-warnings",
        cwd=str(REPO_ROOT),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        raise RuntimeError(stderr_text or stdout_text or "porchlight_failed")
    try:
        return _parse_porchlight_json(stdout_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("porchlight_returned_invalid_json") from exc


def _parse_porchlight_json(stdout_text: str) -> dict:
    try:
        parsed = json.loads(stdout_text)
    except json.JSONDecodeError:
        start = stdout_text.find("{")
        end = stdout_text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(stdout_text[start : end + 1])
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("porchlight_json_not_object", stdout_text, 0)
    return parsed
