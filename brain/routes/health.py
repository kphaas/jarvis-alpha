"""
health.py — Health and LaunchAgent status endpoints for jarvis-alpha Brain.
"""

import asyncio
import subprocess
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter

from brain.services.temporal_storage_monitor import collect_temporal_storage_snapshot
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


def _classify_agent_status(pid: Optional[int], exit_code: Optional[int]) -> str:
    """Classify a LaunchAgent's current state.

    Big-tech rule: A process with a current PID is RUNNING. The previous
    instance's exit code is irrelevant — what matters is whether something
    is alive RIGHT NOW.

    States:
      running   - process has a current PID (it's alive, regardless of past exits)
      idle      - no PID, last exit clean (0) — agent is loaded but not currently
                  running (e.g., periodic agents between runs)
      stopped   - no PID, last exit was a clean signal (-15 SIGTERM, -2 SIGINT)
                  meaning someone intentionally stopped it (kickstart, manual unload)
      error     - no PID, last exit was non-zero and not a clean signal
                  meaning the process crashed
      unknown   - exit code not parseable

    The previous bug: the old logic marked anything with exit_code != 0 as
    "error" — even processes currently running after a `launchctl kickstart -k`,
    which leaves the previous PID's exit code as -15 (SIGTERM). This caused
    Brain to show as ERROR on the Health page after every clean restart.
    """
    # Rule 1: If there's a current PID, the process is running. Period.
    # The previous instance's exit code does not matter.
    if pid is not None:
        return "running"

    # Rule 2: No current PID. Now we look at how it last exited.
    if exit_code is None:
        return "unknown"

    # Clean exit codes
    if exit_code == 0:
        return "idle"

    # Clean signals (intentional stops)
    # -15 = SIGTERM (launchctl kickstart -k, launchctl unload, kill)
    # -2  = SIGINT (Ctrl+C)
    # -1  = SIGHUP
    # -3  = SIGQUIT
    if exit_code in (-15, -2, -1, -3):
        return "stopped"

    # Anything else is a real crash (-9 SIGKILL, -6 SIGABRT, positive non-zero, etc.)
    return "error"


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
            status = _classify_agent_status(pid, exit_code)
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


@router.get("/v1/health/temporal-storage")
async def health_temporal_storage():
    """Return Temporal persistence size, row counts, and disk alert state."""
    return await collect_temporal_storage_snapshot()
