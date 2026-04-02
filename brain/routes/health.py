"""
health.py — Health and LaunchAgent status endpoints for jarvis-alpha Brain.
"""

import asyncio
import subprocess
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter

log = logging.getLogger(__name__)
router = APIRouter()

BRAIN_AGENTS = [
    "com.jarvis.alpha.brain",
    "com.jarvis.alpha.buddy",
    "com.jarvis.ollama",
    "com.jarvis.agentworker",
    "com.jarvis.policy",
    "com.jarvis.auth",
    "com.jarvis.ingestservice",
    "com.jarvis.watchdog",
    "com.jarvis.weeklyreport",
    "com.jarvis.weeklybackup",
    "com.jarvis.certrenew",
    "com.jarvis.cleanup",
    "com.jarvis.mountwatch",
    "com.jarvis.sshagent",
    "com.jarvis.ingest.scheduler",
]


def _safe_int(val: str) -> Optional[int]:
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _parse_launchctl() -> list:
    """Run launchctl list, return parsed entries for known JARVIS agents."""
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        parsed = {}
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            pid_raw, exit_raw, label = parts
            if not label.startswith("com.jarvis."):
                continue
            pid = None if pid_raw.strip() == "-" else _safe_int(pid_raw.strip())
            exit_code = _safe_int(exit_raw.strip())
            running = pid is not None
            if exit_code == 0 and running:
                status = "running"
            elif exit_code == 0 and not running:
                status = "idle"
            else:
                status = "error"
            parsed[label] = {
                "label": label,
                "pid": pid,
                "exit_code": exit_code,
                "status": status,
            }
        out = []
        for label in BRAIN_AGENTS:
            out.append(
                parsed.get(
                    label,
                    {
                        "label": label,
                        "pid": None,
                        "exit_code": None,
                        "status": "not_found",
                    },
                )
            )
        return out
    except Exception as e:
        log.error("launchctl parse failed: %s", e)
        return []


@router.get("/health")
async def health():
    return {"status": "ok", "node": "brain", "service": "jarvis-alpha"}


@router.get("/v1/health/agents")
async def health_agents():
    """Return LaunchAgent status for all known Brain agents."""
    agents = await asyncio.to_thread(_parse_launchctl)
    return {
        "node": "brain",
        "agents": agents,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
