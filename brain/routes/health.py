"""
health.py — Health and LaunchAgent status endpoints for jarvis-alpha Brain.
"""

import asyncio
import subprocess
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter

from jarvis_common.logging_config import get_logger

log = get_logger("alpha_brain")
router = APIRouter()

# Only list agents that have installed LaunchAgent plists.
# Add new entries here AFTER creating the plist — never list stubs.
BRAIN_AGENTS = [
    # Alpha core
    "com.jarvis.alpha.brain",
    "com.jarvis.alpha.buddy",
    # Infrastructure
    "com.jarvis.ollama",
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
