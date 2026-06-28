"""
health.py — Health and LaunchAgent status endpoints for jarvis-alpha Brain.
"""

import asyncio
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from brain.health_probes import (
    ProbeResult,
    probe_db_pool,
    probe_ollama,
    probe_temporal,
)
from brain.services.temporal_storage_monitor import collect_temporal_storage_snapshot
from jarvis_common.logging_config import get_logger

log = get_logger("alpha_brain")
router = APIRouter()
MAINTAINER_STALE_AFTER_HOURS = 24
MAINTAINER_CANDIDATE_FIELDS = (
    "id",
    "node",
    "layer",
    "package",
    "from_ver",
    "to_ver",
    "semver_delta",
    "tier",
    "state",
    "detected_at",
)

# Only list agents that have installed LaunchAgent plists.
# Add new entries here AFTER creating the plist — never list stubs.
BRAIN_AGENTS = [
    # Alpha core
    "com.jarvis.alpha.brain",
    "com.jarvis.alpha.buddy",
    "com.jarvis.alpha.executor",
    "com.jarvis.alpha.watchdog",
    # Observability
    "com.jarvis.alpha.fluentbit",
    "com.jarvis.alpha.loki",
    # Temporal
    "com.jarvis.alpha.temporal.server",
    "com.jarvis.alpha.temporal.ui",
    "com.jarvis.alpha.temporal.worker",
    # Telemetry
    "com.jarvis.alpha.power.brain",
    # Infrastructure
    "com.jarvis.ollama",
]

MAINTAINER_REPORT_ENV = "JARVIS_MAINTAINER_REPORT_PATH"


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


def _maintainer_report_path() -> Path:
    configured = os.getenv(MAINTAINER_REPORT_ENV)
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "jarvis-maintainer" / "var" / "maintainer_report.json"


def _maintainer_missing(path: Path) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat()
    return {
        "status": "missing",
        "source": "jarvis-maintainer",
        "authority": "none",
        "path": str(path),
        "candidate_count": 0,
        "candidate_count_by_tier": {},
        "candidates": [],
        "drift_count": 0,
        "inventory_count": 0,
        "inventory_rows_recorded": 0,
        "new_or_existing_candidate_ids": [],
        "node": None,
        "last_scan_at": None,
        "scan_age_hours": None,
        "scan_stale_after_hours": MAINTAINER_STALE_AFTER_HOURS,
        "is_stale": False,
        "checked_at": checked_at,
    }


def _maintainer_invalid(path: Path, error: str) -> dict[str, Any]:
    payload = _maintainer_missing(path)
    payload["status"] = "invalid"
    payload["error"] = error[:200]
    return payload


def _maintainer_int(raw: Any) -> int:
    return raw if isinstance(raw, int) else 0


def _maintainer_candidates(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        row = {
            field: item.get(field) if isinstance(item.get(field), str) else ""
            for field in MAINTAINER_CANDIDATE_FIELDS
        }
        if row["id"]:
            rows.append(row)
    return rows


def _maintainer_scan_age_hours(last_scan_at: Any, now: datetime) -> float | None:
    if not isinstance(last_scan_at, str) or not last_scan_at:
        return None
    try:
        parsed = datetime.fromisoformat(last_scan_at.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(last_scan_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return round(max(0.0, (now - parsed).total_seconds() / 3600), 2)


def _maintainer_report_payload(report: dict[str, Any], path: Path) -> dict[str, Any]:
    tiers = report.get("candidate_count_by_tier")
    candidate_ids = report.get("new_or_existing_candidate_ids")
    now = datetime.now(timezone.utc)
    scan_age_hours = _maintainer_scan_age_hours(report.get("last_scan_at"), now)
    is_stale = scan_age_hours is None or scan_age_hours > MAINTAINER_STALE_AFTER_HOURS
    return {
        "status": "stale" if is_stale else "ok",
        "source": "jarvis-maintainer",
        "authority": report.get("authority")
        if report.get("authority") == "none"
        else "none",
        "path": str(path),
        "candidate_count": _maintainer_int(report.get("candidate_count")),
        "candidate_count_by_tier": tiers if isinstance(tiers, dict) else {},
        "candidates": _maintainer_candidates(report.get("candidates")),
        "drift_count": _maintainer_int(report.get("drift_count")),
        "inventory_count": _maintainer_int(report.get("inventory_count")),
        "inventory_rows_recorded": _maintainer_int(
            report.get("inventory_rows_recorded")
        ),
        "new_or_existing_candidate_ids": candidate_ids
        if isinstance(candidate_ids, list)
        else [],
        "node": report.get("node") if isinstance(report.get("node"), str) else None,
        "last_scan_at": report.get("last_scan_at")
        if isinstance(report.get("last_scan_at"), str)
        else None,
        "scan_age_hours": scan_age_hours,
        "scan_stale_after_hours": MAINTAINER_STALE_AFTER_HOURS,
        "is_stale": is_stale,
        "checked_at": now.isoformat(),
    }


@router.get("/health")
async def health():
    return {"status": "ok", "node": "brain", "service": "jarvis-alpha"}


def _check_body(r: ProbeResult) -> dict:
    return {
        "ok": r.ok,
        "latency_ms": r.latency_ms,
        "last_error_msg": r.last_error_msg,
    }


@router.get("/health/ready")
async def health_ready():
    """Deep readiness probe (AUDIT-3).

    Probes the three critical dependencies in parallel (fresh, uncached):
    DB pool, Ollama, Temporal. Returns HTTP 200 if all pass, HTTP 503 if any
    fails (including timeout). Status report only — no auto-recovery, no alert
    firing, no retry. Existing /health stays a shallow liveness check.
    """
    db, ollama, temporal = await asyncio.gather(
        probe_db_pool(),
        probe_ollama(),
        probe_temporal(),
        return_exceptions=False,
    )

    checks = {
        "db": _check_body(db),
        "ollama": _check_body(ollama),
        "temporal": _check_body(temporal),
    }
    all_ok = db.ok and ollama.ok and temporal.ok
    body = {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    if all_ok:
        return body

    failed = [name for name, c in checks.items() if not c["ok"]]
    log.warning("health_ready degraded — failed checks: %s", ",".join(failed))
    return JSONResponse(status_code=503, content=body)


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


@router.get("/v1/health/maintainer")
async def health_maintainer():
    """Return the latest local-only JARVIS Maintainer report."""
    path = _maintainer_report_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _maintainer_missing(path)
    except json.JSONDecodeError as exc:
        log.warning("maintainer report invalid json: %s", exc)
        return _maintainer_invalid(path, f"invalid json: {exc}")
    except OSError as exc:
        log.warning("maintainer report unreadable: %s", exc)
        return _maintainer_invalid(path, f"unreadable: {exc}")
    if not isinstance(raw, dict):
        return _maintainer_invalid(path, "report root must be an object")
    return _maintainer_report_payload(raw, path)
