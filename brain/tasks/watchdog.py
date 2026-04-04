"""
TaskGraph Watchdog — runs as LaunchAgent on Brain.
Detects stuck steps and marks them for retry or escalation.
Runs every 5 minutes. Isolated failure domain from executor.
"""

from __future__ import annotations

import asyncio
import json
import signal

import asyncpg

from brain.config.logging_config import get_logger, new_trace_id
from brain.config.secrets import get_secret

WATCHDOG_INTERVAL_SECONDS = 300  # 5 minutes
DB_DSN_KEY = "JARVIS_ALPHA_DB_DSN"

log = get_logger("alpha_watchdog")


def _load_dsn() -> str:
    return get_secret(DB_DSN_KEY).strip().strip('"').strip("'")


async def _bind_watchdog_rls(conn: asyncpg.Connection) -> None:
    await conn.execute("SELECT set_config('jarvis.current_user', 'admin', true)")
    await conn.execute("SELECT set_config('jarvis.role', 'admin', true)")


async def check_stuck(pool: asyncpg.Pool) -> None:
    new_trace_id()
    async with pool.acquire() as conn:
        await _bind_watchdog_rls(conn)
        stuck = await conn.fetch(
            """
            SELECT s.id, s.graph_id, s.step_name, s.timeout_seconds,
                   s.retry_count, s.max_retries,
                   EXTRACT(EPOCH FROM (now() - s.started_at)) AS running_seconds
            FROM alpha_task_steps s
            WHERE s.status = 'running'
              AND s.started_at IS NOT NULL
              AND EXTRACT(EPOCH FROM (now() - s.started_at)) > s.timeout_seconds
            """,
        )

        for row in stuck:
            step_id = row["id"]
            retry_count = row["retry_count"] + 1
            max_retries = row["max_retries"] or 2

            if retry_count <= max_retries:
                await conn.execute(
                    """
                    UPDATE alpha_task_steps
                    SET status = 'pending', retry_count = $2,
                        error_message = 'Watchdog: stuck — timeout exceeded, retrying',
                        updated_at = now()
                    WHERE id = $1
                    """,
                    step_id,
                    retry_count,
                )
                log.warning(
                    "Watchdog: step %s stuck — reset to pending (retry %s)",
                    step_id,
                    retry_count,
                )
                evt_type = "step_retrying"
                pri = "high"
            else:
                await conn.execute(
                    """
                    UPDATE alpha_task_steps
                    SET status = 'stuck',
                        error_message = 'Watchdog: stuck — max retries exceeded',
                        updated_at = now()
                    WHERE id = $1
                    """,
                    step_id,
                )
                await conn.execute(
                    """
                    UPDATE alpha_task_graphs
                    SET status = 'stuck', updated_at = now()
                    WHERE id = $1
                    """,
                    row["graph_id"],
                )
                log.error(
                    "Watchdog: step %s stuck permanently — graph %s marked stuck",
                    step_id,
                    row["graph_id"],
                )
                evt_type = "step_failed"
                pri = "critical"

            detail = json.dumps(
                {
                    "step_id": str(step_id),
                    "graph_id": str(row["graph_id"]),
                    "running_seconds": float(row["running_seconds"] or 0),
                    "retry_count": retry_count,
                }
            )
            try:
                await conn.execute(
                    """
                    INSERT INTO alpha_task_events (
                        event_type, graph_id, step_id, message, priority
                    )
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    evt_type,
                    row["graph_id"],
                    step_id,
                    detail,
                    pri,
                )
            except Exception as exc:
                log.warning("Watchdog: could not write alpha_task_events: %s", exc)

        orphaned = await conn.fetch(
            """
            SELECT g.id FROM alpha_task_graphs g
            WHERE g.status = 'running'
              AND NOT EXISTS (
                  SELECT 1 FROM alpha_task_steps s
                  WHERE s.graph_id = g.id AND s.status IN ('pending', 'queued', 'running')
              )
              AND EXISTS (
                  SELECT 1 FROM alpha_task_steps s
                  WHERE s.graph_id = g.id AND s.status IN ('failed', 'stuck')
              )
            """,
        )
        for orow in orphaned:
            await conn.execute(
                "UPDATE alpha_task_graphs SET status = 'failed', updated_at = now() WHERE id = $1",
                orow["id"],
            )
            log.warning("Watchdog: orphaned graph %s marked failed", orow["id"])


async def main() -> None:
    dsn = _load_dsn()
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    shutdown = asyncio.Event()

    def handle_signal(sig, frame):
        shutdown.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    log.info("TaskGraph watchdog started — interval: %ss", WATCHDOG_INTERVAL_SECONDS)

    while not shutdown.is_set():
        try:
            await check_stuck(pool)
        except Exception as e:
            log.error("Watchdog error: %s", e)

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=WATCHDOG_INTERVAL_SECONDS)
        except TimeoutError:
            pass

    await pool.close()
    log.info("Watchdog shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
