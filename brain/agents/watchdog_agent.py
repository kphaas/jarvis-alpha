"""
watchdog_agent.py — Service health monitoring + self-healing.

Runs as a LaunchAgent on every node. Queries alpha_node_registry to discover
services, pings /health, tracks consecutive failures, kills unhealthy local
processes so launchd KeepAlive can restart them, and writes state changes to
alpha_watchdog_events.
"""

from __future__ import annotations

import asyncio
import os
import platform
import signal
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import asyncpg

from brain.config.secrets import get_secret
from jarvis_common.logging_config import get_logger, new_trace_id

logger = get_logger("alpha_watchdog")

WATCHDOG_INTERVAL = int(os.environ.get("WATCHDOG_INTERVAL_SECONDS", "60"))
FAILURE_THRESHOLD = int(os.environ.get("WATCHDOG_FAILURE_THRESHOLD", "3"))
CHECK_TIMEOUT = int(os.environ.get("WATCHDOG_CHECK_TIMEOUT_SECONDS", "5"))
NODE_NAME = os.environ.get("JARVIS_NODE", platform.node().split(".")[0].lower())

LOCAL_SERVICE_PORTS: dict[str, int] = {
    "brain": 8186,
    "gateway": 8283,
    "endpoint": 4100,
    "sandbox": 5001,
}


@dataclass
class ServiceState:
    name: str
    node: str
    health_endpoint: str
    consecutive_failures: int = 0
    last_status: str = "unknown"
    last_check_at: datetime | None = None
    last_latency_ms: float | None = None
    restart_attempts: int = 0
    trace_id: str = field(default_factory=new_trace_id)


_service_state: dict[str, ServiceState] = {}


async def _check_service(
    svc: ServiceState,
) -> tuple[bool, int | None, float | None, str | None]:
    def _run_curl() -> tuple[bool, int | None, float | None, str | None]:
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-sk",
                    "--max-time",
                    str(CHECK_TIMEOUT),
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}|%{time_total}",
                    svc.health_endpoint,
                ],
                capture_output=True,
                text=True,
                timeout=CHECK_TIMEOUT + 2,
            )
            if result.returncode != 0:
                return (
                    False,
                    None,
                    None,
                    f"curl exit {result.returncode}: {result.stderr.strip()[:200]}",
                )
            if "|" not in result.stdout:
                return (
                    False,
                    None,
                    None,
                    f"malformed curl output: {result.stdout[:100]}",
                )

            code_s, time_s = result.stdout.strip().split("|", 1)
            code = int(code_s) if code_s.isdigit() else None
            latency = float(time_s) * 1000.0 if time_s else None

            is_healthy = code in (200, 401)
            error = None if is_healthy else f"HTTP {code}"
            return is_healthy, code, latency, error

        except subprocess.TimeoutExpired:
            return False, None, None, f"timeout after {CHECK_TIMEOUT}s"
        except Exception as e:
            return False, None, None, f"{type(e).__name__}: {str(e)[:200]}"

    return await asyncio.to_thread(_run_curl)


async def _log_event(
    pool: asyncpg.Pool,
    svc: ServiceState,
    event_type: str,
    previous_state: str,
    current_state: str,
    http_status: int | None = None,
    latency_ms: float | None = None,
    error_message: str | None = None,
    action_taken: str | None = None,
) -> None:
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "SELECT public.record_watchdog_event($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                svc.name,
                svc.node,
                event_type,
                previous_state,
                current_state,
                svc.consecutive_failures,
                latency_ms,
                http_status,
                error_message,
                action_taken,
                uuid.uuid5(uuid.NAMESPACE_DNS, f"watchdog:{svc.trace_id}")
                if svc.trace_id
                else None,
            )
        logger.info(
            "watchdog_event service=%s node=%s type=%s prev=%s curr=%s action=%s",
            svc.name,
            svc.node,
            event_type,
            previous_state,
            current_state,
            action_taken or "-",
        )
    except Exception as e:
        logger.error("failed to log watchdog event: %s", e, exc_info=True)


def _is_local_service(service_name: str) -> bool:
    return service_name == NODE_NAME or (
        NODE_NAME == "brain" and service_name == "brain"
    )


async def _kill_local_service(service_name: str) -> tuple[bool, str]:
    port = LOCAL_SERVICE_PORTS.get(service_name)
    if not port:
        return False, f"no known port for {service_name}"

    def _do_kill() -> tuple[bool, str]:
        try:
            lsof = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            pids = [
                int(p) for p in lsof.stdout.strip().split("\n") if p.strip().isdigit()
            ]
            if not pids:
                return False, f"no process on port {port}"

            killed = []
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                    killed.append(pid)
                except ProcessLookupError:
                    continue
                except PermissionError:
                    return False, f"permission denied killing pid {pid}"

            return True, f"sent SIGTERM to pid(s) {killed} on port {port}"

        except subprocess.TimeoutExpired:
            return False, "lsof timeout"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    return await asyncio.to_thread(_do_kill)


async def _load_services(pool: asyncpg.Pool) -> list[ServiceState]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT name, health_endpoint, node_type
            FROM alpha_node_registry
            WHERE health_endpoint IS NOT NULL
              AND health_endpoint != ''
              AND node_type = 'service'
              AND is_active = true
            ORDER BY name
            """
        )

    services = []
    for row in rows:
        name = row["name"]
        if name in _service_state:
            svc = _service_state[name]
            svc.health_endpoint = row["health_endpoint"]
        else:
            svc = ServiceState(
                name=name,
                node=name,
                health_endpoint=row["health_endpoint"],
            )
            _service_state[name] = svc
        services.append(svc)

    return services


async def _check_and_heal(pool: asyncpg.Pool, svc: ServiceState) -> None:
    is_healthy, http_status, latency_ms, error = await _check_service(svc)
    previous_state = svc.last_status
    svc.last_check_at = datetime.now(timezone.utc)
    svc.last_latency_ms = latency_ms

    if is_healthy:
        if svc.last_status == "down":
            svc.consecutive_failures = 0
            svc.last_status = "up"
            svc.restart_attempts = 0
            svc.trace_id = new_trace_id()
            await _log_event(
                pool,
                svc,
                event_type="restored",
                previous_state=previous_state,
                current_state="up",
                http_status=http_status,
                latency_ms=latency_ms,
                action_taken=None,
            )
        else:
            svc.last_status = "up"
            svc.consecutive_failures = 0
        return

    svc.consecutive_failures += 1
    logger.warning(
        "watchdog: %s unhealthy (%d/%d) — %s",
        svc.name,
        svc.consecutive_failures,
        FAILURE_THRESHOLD,
        error,
    )

    if svc.last_status == "up":
        svc.last_status = "down"
        await _log_event(
            pool,
            svc,
            event_type="down",
            previous_state=previous_state,
            current_state="down",
            http_status=http_status,
            latency_ms=latency_ms,
            error_message=error,
        )

    if svc.consecutive_failures >= FAILURE_THRESHOLD:
        if _is_local_service(svc.name):
            svc.restart_attempts += 1
            await _log_event(
                pool,
                svc,
                event_type="restart_triggered",
                previous_state=svc.last_status,
                current_state="down",
                error_message=error,
                action_taken=f"attempt #{svc.restart_attempts}",
            )

            success, details = await _kill_local_service(svc.name)

            await _log_event(
                pool,
                svc,
                event_type="restart_succeeded" if success else "restart_failed",
                previous_state="down",
                current_state="down",
                error_message=None if success else details,
                action_taken=details,
            )

            svc.consecutive_failures = 0
        else:
            await _log_event(
                pool,
                svc,
                event_type="degraded",
                previous_state=svc.last_status,
                current_state="down",
                error_message=error,
                action_taken="remote — logged only, no local action possible",
            )
            svc.consecutive_failures = 0


async def watchdog_loop(pool: asyncpg.Pool) -> None:
    logger.info(
        "watchdog starting — node=%s interval=%ds threshold=%d",
        NODE_NAME,
        WATCHDOG_INTERVAL,
        FAILURE_THRESHOLD,
    )

    while True:
        try:
            services = await _load_services(pool)
            if not services:
                logger.warning("watchdog: no services to monitor")
            else:
                await asyncio.gather(
                    *[_check_and_heal(pool, svc) for svc in services],
                    return_exceptions=True,
                )

            up = sum(1 for s in _service_state.values() if s.last_status == "up")
            down = sum(1 for s in _service_state.values() if s.last_status == "down")
            logger.info(
                "watchdog cycle complete — up=%d down=%d total=%d",
                up,
                down,
                len(_service_state),
            )

        except Exception as e:
            logger.error("watchdog loop error: %s", e, exc_info=True)

        await asyncio.sleep(WATCHDOG_INTERVAL)


async def main() -> None:
    dsn = get_secret("ALPHA_DB_DSN_WATCHDOG_AGENT")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    try:
        await watchdog_loop(pool)
    finally:
        await pool.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        logger.error(
            "Watchdog agent crashed — unhandled exception: %s",
            exc,
            exc_info=True,
        )
        raise
