"""
TaskGraph Executor — runs as LaunchAgent on Brain.
Polls for pending graphs, walks DAG, dispatches steps.
Architecture: Stanford task DAG + AWS Step Functions pattern.

Also exports TaskGraphExecutor and recover_stuck_graphs for in-process use (FastAPI).
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import Any
from uuid import UUID

import asyncpg

from brain.config.secrets import get_secret
from brain.tasks.dispatch import (
    call_code_agent,
    call_llm_agent,
    call_tool_agent,
    dispatch,
)

# --------------- config ---------------

MAX_CONCURRENT_GRAPHS = 3
POLL_INTERVAL_SECONDS = 10
DB_DSN_KEY = "JARVIS_ALPHA_DB_DSN"

# --------------- logging ---------------

logging.basicConfig(
    level=logging.INFO,
    format=json.dumps(
        {
            "timestamp": "%(asctime)s",
            "level": "%(levelname)s",
            "service": "alpha_executor",
            "node": "brain",
            "message": "%(message)s",
        }
    ),
)
log = logging.getLogger("alpha_executor")

# --------------- secrets ---------------


def _load_dsn() -> str:
    return get_secret(DB_DSN_KEY).strip().strip('"').strip("'")


async def _bind_executor_rls(conn: asyncpg.Connection) -> None:
    await conn.execute("SELECT set_config('jarvis.current_user', 'admin', true)")
    await conn.execute("SELECT set_config('jarvis.role', 'admin', true)")


def _step_dict_llm(step_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "executor": "llm",
        "config": {
            "prompt": step_input.get("prompt", ""),
            "model": step_input.get("model", "llama3.1:8b"),
        },
    }


def _step_dict_code(step_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "executor": "code",
        "config": {
            "prompt": step_input.get("prompt", ""),
            "language": step_input.get("language", "python"),
        },
    }


def _step_dict_tool(step_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "executor": "tool",
        "config": {
            "tool_name": step_input.get("tool_name", ""),
            "params": step_input.get("params", {}),
        },
    }


def _map_dispatch_result(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("success"):
        return {
            "success": True,
            "output": result.get("output") or {},
            "error": None,
        }
    return {
        "success": False,
        "output": {},
        "error": result.get("error") or "dispatch failed",
    }


# --------------- DAG logic ---------------


async def find_ready_steps(conn: asyncpg.Connection, graph_id: UUID) -> list[dict]:
    """Find steps whose dependencies are all completed."""
    rows = await conn.fetch(
        """
        SELECT s.*
        FROM alpha_task_steps s
        WHERE s.graph_id = $1
          AND s.status = 'pending'
          AND NOT EXISTS (
              SELECT 1
              FROM unnest(s.depends_on) AS dep_id
              WHERE dep_id NOT IN (
                  SELECT id FROM alpha_task_steps
                  WHERE graph_id = $1 AND status = 'completed'
              )
          )
        ORDER BY s.step_order
        """,
        graph_id,
    )
    return [dict(r) for r in rows]


async def dispatch_step(_conn: asyncpg.Connection, step: dict) -> dict:
    """
    Execute a single step based on step_type.
    Returns {"success": bool, "output": dict, "error": str|None}
    """
    step_type = step.get("step_type") or "llm"
    content_tier = step.get("content_tier") or "unrestricted"
    step_input = step.get("input") or {}
    if not isinstance(step_input, dict):
        step_input = {}

    # Child safety — child_safe tier: local LLM only (no code/tool agents)
    if content_tier == "child_safe" and step_type in ("tool", "code"):
        return {
            "success": False,
            "output": {},
            "error": "child_safe content tier — only local LLM steps allowed",
        }

    try:
        if step_type == "llm":
            raw = await call_llm_agent(_step_dict_llm(step_input))
            log.info(f"LLM dispatch raw: {raw}")
            return _map_dispatch_result(raw)

        if step_type == "code":
            raw = await call_code_agent(_step_dict_code(step_input))
            return _map_dispatch_result(raw)

        if step_type == "tool":
            raw = await call_tool_agent(_step_dict_tool(step_input))
            return _map_dispatch_result(raw)

        if step_type == "approval":
            return {"success": False, "output": {}, "error": "__APPROVAL_REQUIRED__"}

        if step_type == "condition":
            return {"success": True, "output": {"branch": "default"}, "error": None}

        if step_type == "parallel_gate":
            return {"success": True, "output": {"gate": "passed"}, "error": None}

        return {
            "success": False,
            "output": {},
            "error": f"Unknown step_type: {step_type}",
        }

    except Exception as e:
        log.error("Step %s dispatch error: %s", step["id"], e)
        return {"success": False, "output": {}, "error": str(e)}


async def run_graph(pool: asyncpg.Pool, graph_id: UUID) -> None:
    """Execute a single graph to completion, failure, or approval block."""
    log.info("Starting graph %s", graph_id)

    async with pool.acquire() as conn:
        await _bind_executor_rls(conn)
        await conn.execute(
            """
            UPDATE alpha_task_graphs
            SET status = 'running', started_at = now(), updated_at = now()
            WHERE id = $1
            """,
            graph_id,
        )

        while True:
            graph_status = await conn.fetchval(
                "SELECT status FROM alpha_task_graphs WHERE id = $1",
                graph_id,
            )
            if graph_status == "cancelled":
                log.info("Graph %s cancelled", graph_id)
                return

            ready = await find_ready_steps(conn, graph_id)

            if not ready:
                remaining = await conn.fetchval(
                    """
                    SELECT count(*) FROM alpha_task_steps
                    WHERE graph_id = $1
                      AND status NOT IN ('completed', 'skipped', 'cancelled')
                    """,
                    graph_id,
                )
                if remaining == 0:
                    await conn.execute(
                        """
                        UPDATE alpha_task_graphs
                        SET status = 'completed', completed_at = now(), updated_at = now()
                        WHERE id = $1
                        """,
                        graph_id,
                    )
                    log.info("Graph %s completed", graph_id)
                else:
                    awaiting = await conn.fetchval(
                        """
                        SELECT count(*) FROM alpha_task_steps
                        WHERE graph_id = $1 AND status = 'queued'
                          AND approval_required = true
                          AND approval_status = 'pending'
                        """,
                        graph_id,
                    )
                    if awaiting and int(awaiting) > 0:
                        await conn.execute(
                            """
                            UPDATE alpha_task_graphs
                            SET status = 'needs_approval', updated_at = now()
                            WHERE id = $1
                            """,
                            graph_id,
                        )
                        log.info("Graph %s waiting for approval", graph_id)
                    else:
                        failed_count = await conn.fetchval(
                            """
                            SELECT count(*) FROM alpha_task_steps
                            WHERE graph_id = $1 AND status = 'failed'
                            """,
                            graph_id,
                        )
                        if failed_count and int(failed_count) > 0:
                            await conn.execute(
                                """
                                UPDATE alpha_task_graphs
                                SET status = 'failed', updated_at = now()
                                WHERE id = $1
                                """,
                                graph_id,
                            )
                            log.info(
                                "Graph %s failed — %s failed steps",
                                graph_id,
                                failed_count,
                            )
                        else:
                            log.warning(
                                "Graph %s — no ready steps but %s remaining",
                                graph_id,
                                remaining,
                            )
                return

            for step in ready:
                step_id = step["id"]

                if (
                    step.get("approval_required")
                    and step.get("approval_status") != "approved"
                ):
                    await conn.execute(
                        """
                        UPDATE alpha_task_steps
                        SET status = 'queued', approval_status = 'pending', updated_at = now()
                        WHERE id = $1
                        """,
                        step_id,
                    )
                    log.info("Step %s requires approval — queued", step_id)
                    continue

                await conn.execute(
                    """
                    UPDATE alpha_task_steps
                    SET status = 'running', started_at = now(), updated_at = now()
                    WHERE id = $1
                    """,
                    step_id,
                )

                timeout = step.get("timeout_seconds") or 300
                try:
                    result = await asyncio.wait_for(
                        dispatch_step(conn, step),
                        timeout=timeout,
                    )
                except TimeoutError:
                    result = {
                        "success": False,
                        "output": {},
                        "error": f"Timeout after {timeout}s",
                    }

                if result["error"] == "__APPROVAL_REQUIRED__":
                    await conn.execute(
                        """
                        UPDATE alpha_task_steps
                        SET status = 'queued', approval_status = 'pending',
                            approval_required = true, updated_at = now()
                        WHERE id = $1
                        """,
                        step_id,
                    )
                    continue

                if result["success"]:
                    await conn.execute(
                        """
                        UPDATE alpha_task_steps
                        SET status = 'completed',
                            output = $2::jsonb,
                            completed_at = now(),
                            updated_at = now()
                        WHERE id = $1
                        """,
                        step_id,
                        json.dumps(result["output"]),
                    )
                    log.info("Step %s completed", step_id)
                else:
                    retry_count = (step.get("retry_count") or 0) + 1
                    max_retries = step.get("max_retries") or 2

                    if retry_count <= max_retries:
                        await conn.execute(
                            """
                            UPDATE alpha_task_steps
                            SET status = 'pending',
                                retry_count = $2,
                                error_message = $3,
                                updated_at = now()
                            WHERE id = $1
                            """,
                            step_id,
                            retry_count,
                            result["error"],
                        )
                        log.warning(
                            "Step %s failed — retry %s/%s",
                            step_id,
                            retry_count,
                            max_retries,
                        )
                    else:
                        await conn.execute(
                            """
                            UPDATE alpha_task_steps
                            SET status = 'failed',
                                error_message = $2,
                                retry_count = $3,
                                updated_at = now()
                            WHERE id = $1
                            """,
                            step_id,
                            result["error"],
                            retry_count,
                        )
                        await conn.execute(
                            """
                            UPDATE alpha_task_steps
                            SET status = 'skipped', updated_at = now()
                            WHERE graph_id = $1
                              AND $2 = ANY(depends_on)
                              AND status = 'pending'
                            """,
                            step.get("graph_id"),
                            step_id,
                        )
                        log.error(
                            "Step %s failed permanently — downstream skipped",
                            step_id,
                        )


async def _run_graph_with_semaphore(
    pool: asyncpg.Pool, graph_id: UUID, semaphore: asyncio.Semaphore
) -> None:
    async with semaphore:
        await run_graph(pool, graph_id)


# --------------- main loop ---------------


async def main() -> None:
    dsn = _load_dsn()
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=5)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_GRAPHS)
    shutdown = asyncio.Event()

    def handle_signal(sig, frame):
        log.info("Received signal %s — shutting down", sig)
        shutdown.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    log.info("TaskGraph executor started — max concurrency: %s", MAX_CONCURRENT_GRAPHS)

    while not shutdown.is_set():
        try:
            async with pool.acquire() as conn:
                await _bind_executor_rls(conn)
                graphs = await conn.fetch(
                    """
                    SELECT id FROM alpha_task_graphs
                    WHERE status IN ('pending', 'running')
                    ORDER BY priority DESC, created_at ASC
                    LIMIT $1
                    """,
                    MAX_CONCURRENT_GRAPHS,
                )

                approved_graphs = await conn.fetch(
                    """
                    SELECT DISTINCT g.id
                    FROM alpha_task_graphs g
                    JOIN alpha_task_steps s ON s.graph_id = g.id
                    WHERE g.status = 'needs_approval'
                      AND s.approval_required = true
                      AND s.approval_status = 'approved'
                      AND s.status = 'queued'
                    """,
                )

            all_graph_ids = list(
                {r["id"] for r in graphs} | {r["id"] for r in approved_graphs}
            )

            if all_graph_ids:
                tasks = [
                    asyncio.create_task(_run_graph_with_semaphore(pool, gid, semaphore))
                    for gid in all_graph_ids
                ]
                await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            log.error("Executor loop error: %s", e)

        try:
            await asyncio.wait_for(shutdown.wait(), timeout=POLL_INTERVAL_SECONDS)
        except TimeoutError:
            pass

    await pool.close()
    log.info("Executor shutdown complete")


# ---------------------------------------------------------------------------
# In-process API (existing FastAPI wiring)
# ---------------------------------------------------------------------------


class TaskGraphExecutor:
    def __init__(self, db_pool: asyncpg.Pool, max_concurrent: int = 3) -> None:
        self.pool = db_pool
        self._sem = asyncio.Semaphore(max_concurrent)

    @staticmethod
    async def _bind_worker_rls(conn: asyncpg.Connection) -> None:
        await conn.execute("SELECT set_config('jarvis.current_user', 'admin', true)")
        await conn.execute("SELECT set_config('jarvis.role', 'admin', true)")

    async def notify(
        self,
        event_type: str,
        graph_id: str,
        step_id: str | None = None,
        message: str = "",
        priority: str = "normal",
    ) -> None:
        try:
            async with self.pool.acquire() as conn:
                await self._bind_worker_rls(conn)
                sid = step_id if step_id else None
                await conn.execute(
                    """
                    INSERT INTO alpha_task_events (
                        event_type, graph_id, step_id, message, priority
                    )
                    VALUES ($1, $2::uuid, $3, $4, $5)
                    """,
                    event_type,
                    graph_id,
                    sid,
                    message,
                    priority,
                )
        except Exception as exc:
            print(f"notify failed: {exc}", flush=True)

    async def resolve_ready_steps(self, graph_id: str) -> list[str]:
        async with self.pool.acquire() as conn:
            await self._bind_worker_rls(conn)
            rows = await conn.fetch(
                """
                SELECT id, depends_on, status
                FROM alpha_task_steps
                WHERE graph_id = $1::uuid
                """,
                graph_id,
            )
        by_id: dict[str, Any] = {str(r["id"]): r for r in rows}
        ready: list[str] = []
        for r in rows:
            if r["status"] != "pending":
                continue
            deps = r["depends_on"] or []
            if not deps:
                ready.append(str(r["id"]))
                continue
            if all(
                str(d) in by_id and by_id[str(d)]["status"] == "complete" for d in deps
            ):
                ready.append(str(r["id"]))
        return ready

    async def execute_step(self, step_id: str) -> None:
        async with self.pool.acquire() as conn:
            await self._bind_worker_rls(conn)
            await conn.execute(
                """
                UPDATE alpha_task_steps
                SET status = 'running',
                    started_at = COALESCE(started_at, NOW())
                WHERE id = $1::uuid
                """,
                step_id,
            )
            step = await conn.fetchrow(
                """
                SELECT id, graph_id, label, depends_on, status, retry_count,
                       executor, tool, input, output, error, checkpoint
                FROM alpha_task_steps
                WHERE id = $1::uuid
                """,
                step_id,
            )
        if step is None:
            return
        graph_id = str(step["graph_id"])
        try:
            result = await dispatch(dict(step))
            if not result.get("success"):
                raise RuntimeError(result.get("error") or "dispatch failed")
            out = result.get("output") or {}
        except Exception as exc:
            err = str(exc)
            should_retry = False
            should_fail = False
            async with self.pool.acquire() as conn:
                await self._bind_worker_rls(conn)
                async with conn.transaction():
                    row = await conn.fetchrow(
                        """
                        SELECT retry_count
                        FROM alpha_task_steps
                        WHERE id = $1::uuid
                        FOR UPDATE
                        """,
                        step_id,
                    )
                    if row is None:
                        return
                    rc = row["retry_count"]
                    if rc < 3:
                        await conn.execute(
                            """
                            UPDATE alpha_task_steps
                            SET retry_count = retry_count + 1,
                                status = 'retrying',
                                error = $2
                            WHERE id = $1::uuid
                            """,
                            step_id,
                            err,
                        )
                        await conn.execute(
                            """
                            UPDATE alpha_task_steps
                            SET status = 'pending'
                            WHERE id = $1::uuid
                            """,
                            step_id,
                        )
                        should_retry = True
                    else:
                        await conn.execute(
                            """
                            UPDATE alpha_task_steps
                            SET status = 'halted',
                                error = $2,
                                completed_at = NOW()
                            WHERE id = $1::uuid
                            """,
                            step_id,
                            err,
                        )
                        should_fail = True
            if should_retry:
                await self.notify("step_retrying", graph_id, step_id, err, "normal")
            elif should_fail:
                await self.notify("step_failed", graph_id, step_id, err, "high")
            return
        async with self.pool.acquire() as conn:
            await self._bind_worker_rls(conn)
            await conn.execute(
                """
                UPDATE alpha_task_steps
                SET status = 'complete',
                    output = $2::jsonb,
                    completed_at = NOW(),
                    error = NULL
                WHERE id = $1::uuid
                """,
                step_id,
                out,
            )

    async def run_graph(self, graph_id: str) -> None:
        async with self._sem:
            async with self.pool.acquire() as conn:
                await self._bind_worker_rls(conn)
                await conn.execute(
                    """
                    UPDATE alpha_task_graphs
                    SET status = 'running',
                        started_at = COALESCE(started_at, NOW())
                    WHERE id = $1::uuid
                    """,
                    graph_id,
                )
            while True:
                ready = await self.resolve_ready_steps(graph_id)
                if not ready:
                    break
                await asyncio.gather(*(self.execute_step(sid) for sid in ready))
            async with self.pool.acquire() as conn:
                await self._bind_worker_rls(conn)
                rows = await conn.fetch(
                    """
                    SELECT status
                    FROM alpha_task_steps
                    WHERE graph_id = $1::uuid
                    """,
                    graph_id,
                )
            statuses = [r["status"] for r in rows]
            if not rows:
                return
            all_done = all(s in ("complete", "skipped") for s in statuses)
            any_halted = any(s in ("halted", "failed") for s in statuses)
            if all_done:
                async with self.pool.acquire() as conn:
                    await self._bind_worker_rls(conn)
                    await conn.execute(
                        """
                        UPDATE alpha_task_graphs
                        SET status = 'complete',
                            completed_at = NOW()
                        WHERE id = $1::uuid
                        """,
                        graph_id,
                    )
            elif any_halted:
                async with self.pool.acquire() as conn:
                    await self._bind_worker_rls(conn)
                    await conn.execute(
                        """
                        UPDATE alpha_task_graphs
                        SET status = 'halted',
                            completed_at = NOW()
                        WHERE id = $1::uuid
                        """,
                        graph_id,
                    )
                await self.notify(
                    "graph_halted",
                    graph_id,
                    None,
                    "One or more steps halted or failed",
                    "high",
                )


async def recover_stuck_graphs(db_pool: asyncpg.Pool) -> None:
    async with db_pool.acquire() as conn:
        await TaskGraphExecutor._bind_worker_rls(conn)
        status = await conn.execute(
            """
            UPDATE alpha_task_graphs
            SET status = 'pending'
            WHERE status = 'running'
            """
        )
    parts = status.split()
    n = int(parts[-1]) if parts else 0
    print(f"Recovered {n} stuck graph(s)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
