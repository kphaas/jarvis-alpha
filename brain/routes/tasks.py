from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncIterator, Literal

import asyncpg
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from brain.db.pool import get_pool
from brain.tasks.executor import TaskGraphExecutor
from brain.tasks.executor import recover_stuck_graphs  # noqa: F401

tasks_router = APIRouter(tags=["tasks"])

_executor: TaskGraphExecutor | None = None


def _get_executor() -> TaskGraphExecutor:
    global _executor
    if _executor is None:
        _executor = TaskGraphExecutor(get_pool(), max_concurrent=3)
    return _executor


@asynccontextmanager
async def _rls_conn(request: Request) -> AsyncIterator[asyncpg.Connection]:
    pool = get_pool()
    user_id = getattr(request.state, "user_id", "anon")
    role = getattr(request.state, "role", "user")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "SELECT set_config('jarvis.current_user', $1, true)",
                user_id,
            )
            await conn.execute(
                "SELECT set_config('jarvis.role', $1, true)",
                role,
            )
            yield conn


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


class CreateGraphBody(BaseModel):
    title: str
    source: Literal["manual", "agent"]
    ci_required: bool = False


class CreateStepBody(BaseModel):
    label: str
    depends_on: list[str] = Field(default_factory=list)
    executor: str
    tool: str | None = None
    input: dict[str, Any] = Field(default_factory=dict)


@tasks_router.post("/v1/tasks/graphs")
async def post_graph(request: Request, body: CreateGraphBody) -> dict[str, str]:
    user_id = getattr(request.state, "user_id", "anon")
    async with _rls_conn(request) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO alpha_task_graphs (
                title, created_by, source, status, ci_required
            )
            VALUES ($1, $2, $3, 'pending', $4)
            RETURNING id::text
            """,
            body.title,
            user_id,
            body.source,
            body.ci_required,
        )
    if row is None:
        raise HTTPException(status_code=500, detail="insert failed")
    return {"graph_id": row["id"]}


@tasks_router.get("/v1/tasks/graphs")
async def list_graphs(
    request: Request,
    status: str | None = Query(default=None),
) -> list[dict[str, Any]]:
    async with _rls_conn(request) as conn:
        rows = await conn.fetch(
            """
            SELECT g.id, g.title, g.source, g.status, g.ci_required, g.ci_passed,
                   g.created_at,
                   COUNT(s.id)::bigint AS step_count
            FROM alpha_task_graphs g
            LEFT JOIN alpha_task_steps s ON s.graph_id = g.id
            WHERE ($1::text IS NULL OR g.status = $1)
            GROUP BY g.id, g.title, g.source, g.status, g.ci_required,
                     g.ci_passed, g.created_at
            ORDER BY g.created_at DESC
            """,
            status,
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": str(r["id"]),
                "title": r["title"],
                "source": r["source"],
                "status": r["status"],
                "ci_required": r["ci_required"],
                "ci_passed": r["ci_passed"],
                "created_at": _iso(r["created_at"]),
                "step_count": int(r["step_count"]),
            }
        )
    return out


@tasks_router.get("/v1/tasks/graphs/{graph_id}")
async def get_graph(request: Request, graph_id: str) -> dict[str, Any]:
    async with _rls_conn(request) as conn:
        graph = await conn.fetchrow(
            """
            SELECT id, title, created_by, source, status, ci_required, ci_passed,
                   checkpoint, created_at, started_at, completed_at
            FROM alpha_task_graphs
            WHERE id = $1::uuid
            """,
            graph_id,
        )
        if graph is None:
            raise HTTPException(status_code=404, detail="graph not found")
        steps = await conn.fetch(
            """
            SELECT id, graph_id, label, depends_on, status, retry_count,
                   executor, tool, input, output, error, checkpoint,
                   started_at, completed_at
            FROM alpha_task_steps
            WHERE graph_id = $1::uuid
            ORDER BY id
            """,
            graph_id,
        )
    g = dict(graph)
    g["id"] = str(g["id"])
    for k in ("created_at", "started_at", "completed_at"):
        if k in g:
            g[k] = _iso(g[k]) if g[k] is not None else None
    step_list = []
    for s in steps:
        d = dict(s)
        d["id"] = str(d["id"])
        d["graph_id"] = str(d["graph_id"])
        if d.get("depends_on") is not None:
            d["depends_on"] = [str(x) for x in d["depends_on"]]
        for k in ("started_at", "completed_at"):
            if k in d:
                d[k] = _iso(d[k]) if d[k] is not None else None
        step_list.append(d)
    return {"graph": g, "steps": step_list}


@tasks_router.post("/v1/tasks/graphs/{graph_id}/steps")
async def post_step(
    request: Request, graph_id: str, body: CreateStepBody
) -> dict[str, str]:
    dep_uuids: list[uuid.UUID] = []
    for d in body.depends_on:
        try:
            dep_uuids.append(uuid.UUID(d))
        except ValueError as e:
            raise HTTPException(
                status_code=400, detail=f"invalid depends_on uuid: {d}"
            ) from e
    async with _rls_conn(request) as conn:
        ok = await conn.fetchval(
            "SELECT 1 FROM alpha_task_graphs WHERE id = $1::uuid",
            graph_id,
        )
        if ok is None:
            raise HTTPException(status_code=404, detail="graph not found")
        row = await conn.fetchrow(
            """
            INSERT INTO alpha_task_steps (
                graph_id, label, depends_on, status, executor, tool, input
            )
            VALUES ($1::uuid, $2, $3::uuid[], 'pending', $4, $5, $6::jsonb)
            RETURNING id::text
            """,
            graph_id,
            body.label,
            dep_uuids,
            body.executor,
            body.tool,
            body.input,
        )
    if row is None:
        raise HTTPException(status_code=500, detail="insert failed")
    return {"step_id": row["id"]}


@tasks_router.post("/v1/tasks/graphs/{graph_id}/approve")
async def approve_graph(request: Request, graph_id: str) -> dict[str, str]:
    async with _rls_conn(request) as conn:
        row = await conn.fetchrow(
            """
            SELECT ci_required, ci_passed
            FROM alpha_task_graphs
            WHERE id = $1::uuid
            FOR UPDATE
            """,
            graph_id,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="graph not found")
        if row["ci_required"] and row["ci_passed"] is not True:
            raise HTTPException(
                status_code=400,
                detail="CI must pass before approval",
            )
        await conn.execute(
            """
            UPDATE alpha_task_graphs
            SET ci_passed = true
            WHERE id = $1::uuid
            """,
            graph_id,
        )
    asyncio.create_task(_get_executor().run_graph(graph_id))
    return {"status": "started", "graph_id": graph_id}


@tasks_router.get("/v1/tasks/graphs/{graph_id}/status")
async def graph_status(request: Request, graph_id: str) -> dict[str, Any]:
    async with _rls_conn(request) as conn:
        graph = await conn.fetchrow(
            """
            SELECT id, status
            FROM alpha_task_graphs
            WHERE id = $1::uuid
            """,
            graph_id,
        )
        if graph is None:
            raise HTTPException(status_code=404, detail="graph not found")
        counts = await conn.fetch(
            """
            SELECT status, COUNT(*)::bigint AS n
            FROM alpha_task_steps
            WHERE graph_id = $1::uuid
            GROUP BY status
            """,
            graph_id,
        )
    keys = ("pending", "running", "complete", "halted", "retrying")
    by_status = {k: 0 for k in keys}
    for r in counts:
        s = r["status"]
        if s in by_status:
            by_status[s] = int(r["n"])
    return {
        "graph_id": str(graph["id"]),
        "status": graph["status"],
        "steps": by_status,
    }


@tasks_router.get("/v1/buddy/events")
async def get_task_buddy_events(
    request: Request,
    limit: int = Query(default=20, ge=1, le=500),
    mark_read: bool = Query(default=False),
) -> list[dict[str, Any]]:
    async with _rls_conn(request) as conn:
        rows = await conn.fetch(
            """
            SELECT id, event_type, graph_id, step_id, message, priority, read, created_at
            FROM alpha_task_events
            WHERE read = false
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
        if mark_read and rows:
            ids = [r["id"] for r in rows]
            await conn.execute(
                """
                UPDATE alpha_task_events
                SET read = true
                WHERE id = ANY($1::uuid[])
                """,
                ids,
            )
    result: list[dict[str, Any]] = []
    for r in rows:
        result.append(
            {
                "id": str(r["id"]),
                "event_type": r["event_type"],
                "graph_id": str(r["graph_id"]) if r["graph_id"] else None,
                "step_id": str(r["step_id"]) if r["step_id"] else None,
                "message": r["message"],
                "priority": r["priority"],
                "read": True if mark_read else r["read"],
                "created_at": _iso(r["created_at"]),
            }
        )
    return result
