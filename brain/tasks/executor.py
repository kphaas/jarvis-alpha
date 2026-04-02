"""
WORKER NODE UPGRADE PATH:
TaskGraphExecutor is intentionally decoupled from FastAPI.
To extract to a standalone worker node:
- Run this file as a standalone asyncio script polling alpha_task_graphs
- dispatch.py handlers become HTTP calls to Brain API
- No changes to this class required
"""

from __future__ import annotations

import asyncio
from typing import Any

import asyncpg

from brain.tasks.dispatch import dispatch


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
