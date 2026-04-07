from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from brain.db.pool import get_pool
from brain.db.rls import rls_connection
from brain.tasks.executor import TaskGraphExecutor
from brain.tasks.executor import recover_stuck_graphs  # noqa: F401

tasks_router = APIRouter(tags=["tasks"])

_executor: TaskGraphExecutor | None = None


def _get_executor() -> TaskGraphExecutor:
    global _executor
    if _executor is None:
        _executor = TaskGraphExecutor(get_pool(), max_concurrent=3)
    return _executor


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
    async with rls_connection(request) as conn:
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
    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            """
            SELECT g.id, g.title, g.graph_type, g.status, g.priority,
                   g.created_at, g.updated_at,
                   COUNT(s.id)::bigint AS step_count
            FROM alpha_task_graphs g
            LEFT JOIN alpha_task_steps s ON s.graph_id = g.id
            WHERE ($1::text IS NULL OR g.status = $1)
            GROUP BY g.id, g.title, g.graph_type, g.status, g.priority,
                     g.created_at, g.updated_at
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
                "graph_type": r["graph_type"],
                "status": r["status"],
                "priority": r["priority"],
                "created_at": _iso(r["created_at"]),
                "updated_at": _iso(r["updated_at"]),
                "step_count": int(r["step_count"]),
            }
        )
    return out


@tasks_router.get("/v1/tasks/graphs/{graph_id}")
async def get_graph(request: Request, graph_id: str) -> dict[str, Any]:
    async with rls_connection(request) as conn:
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
    async with rls_connection(request) as conn:
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
    async with rls_connection(request) as conn:
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
    async with rls_connection(request) as conn:
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


@tasks_router.get("/v1/tasks/events")
async def get_task_buddy_events(
    request: Request,
    limit: int = Query(default=20, ge=1, le=500),
    mark_read: bool = Query(default=False),
) -> list[dict[str, Any]]:
    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            """
            SELECT id, event_type, graph_id, step_id, message, severity, read, created_at
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


# ------------------------------------------------------------------
# SUBMIT — create a new task graph with steps
# ------------------------------------------------------------------


@tasks_router.post("/v1/tasks/submit")
async def submit_graph(request: Request):
    """
    Submit a new TaskGraph for execution.
    Body: {
        "title": str,
        "description": str (optional),
        "graph_type": "overnight" | "user_request" | "agent" | "maintenance",
        "user_type": "adult" | "child",
        "content_tier": "unrestricted" | "filtered" | "child_safe",
        "priority": 1-10 (default 5),
        "steps": [
            {
                "step_name": str,
                "step_type": "llm" | "code" | "tool" | "approval" | "condition" | "parallel_gate",
                "step_order": int,
                "input": {},
                "depends_on_indices": [int] (references step_order of other steps),
                "approval_required": bool (default false),
                "timeout_seconds": int (default 300),
                "max_retries": int (default 2)
            }
        ]
    }
    """
    body = await request.json()
    user_id = getattr(request.state, "user_id", "anon")

    title = body.get("title", "Untitled Graph")
    graph_type = body.get("graph_type", "user_request")
    user_type = body.get("user_type", "adult")
    content_tier = body.get("content_tier", "unrestricted")
    priority = body.get("priority", 5)
    steps_data = body.get("steps", [])

    if not steps_data:
        return JSONResponse({"error": "No steps provided"}, status_code=400)

    async with rls_connection(request) as conn:
        graph_id = await conn.fetchval(
            """
            INSERT INTO alpha_task_graphs
              (user_id, title, description, graph_type, user_type,
               content_tier, priority)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            user_id,
            title,
            body.get("description", ""),
            graph_type,
            user_type,
            content_tier,
            priority,
        )

        step_ids: dict[int, uuid.UUID] = {}
        for s in steps_data:
            step_id = await conn.fetchval(
                """
                INSERT INTO alpha_task_steps
                  (graph_id, user_id, step_name, step_type, step_order,
                   content_tier, input, approval_required,
                   timeout_seconds, max_retries)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10)
                RETURNING id
                """,
                graph_id,
                user_id,
                s.get("step_name", f"step_{s.get('step_order', 0)}"),
                s["step_type"],
                s.get("step_order", 0),
                content_tier,
                json.dumps(s.get("input", {})),
                s.get("approval_required", False),
                s.get("timeout_seconds", 300),
                s.get("max_retries", 2),
            )
            step_ids[s.get("step_order", 0)] = step_id

        for s in steps_data:
            dep_indices = s.get("depends_on_indices", [])
            if dep_indices:
                dep_uuids = [step_ids[i] for i in dep_indices if i in step_ids]
                step_id = step_ids[s.get("step_order", 0)]
                await conn.execute(
                    """
                    UPDATE alpha_task_steps
                    SET depends_on = $2
                    WHERE id = $1
                    """,
                    step_id,
                    dep_uuids,
                )

    return JSONResponse(
        {
            "graph_id": str(graph_id),
            "steps_created": len(step_ids),
            "status": "pending",
        }
    )


# ------------------------------------------------------------------
# APPROVE / DENY — approval gateway
# ------------------------------------------------------------------


@tasks_router.post("/v1/tasks/steps/{step_id}/approve")
async def approve_step(step_id: str, request: Request):
    user_id = getattr(request.state, "user_id", "anon")
    async with rls_connection(request) as conn:
        await conn.execute(
            """
            UPDATE alpha_task_steps
            SET approval_status = 'approved',
                approved_by = $2,
                approved_at = now(),
                updated_at = now()
            WHERE id = $1
              AND approval_required = true
              AND approval_status = 'pending'
            """,
            UUID(step_id),
            str(user_id),
        )
        await conn.execute(
            """
            UPDATE alpha_task_graphs
            SET status = 'running', updated_at = now()
            WHERE id = (SELECT graph_id FROM alpha_task_steps WHERE id = $1)
              AND status = 'needs_approval'
            """,
            UUID(step_id),
        )
    return JSONResponse({"approved": True, "step_id": step_id})


@tasks_router.post("/v1/tasks/steps/{step_id}/deny")
async def deny_step(step_id: str, request: Request):
    user_id = getattr(request.state, "user_id", "anon")
    async with rls_connection(request) as conn:
        await conn.execute(
            """
            UPDATE alpha_task_steps
            SET approval_status = 'denied',
                status = 'cancelled',
                approved_by = $2,
                approved_at = now(),
                updated_at = now()
            WHERE id = $1
            """,
            UUID(step_id),
            str(user_id),
        )
        await conn.execute(
            """
            UPDATE alpha_task_graphs
            SET status = 'failed', updated_at = now()
            WHERE id = (SELECT graph_id FROM alpha_task_steps WHERE id = $1)
            """,
            UUID(step_id),
        )
    return JSONResponse({"denied": True, "step_id": step_id})


# ------------------------------------------------------------------
# CANCEL — stop a running graph
# ------------------------------------------------------------------


@tasks_router.post("/v1/tasks/{graph_id}/cancel")
async def cancel_graph(graph_id: str, request: Request):
    async with rls_connection(request) as conn:
        await conn.execute(
            """
            UPDATE alpha_task_graphs
            SET status = 'cancelled', updated_at = now()
            WHERE id = $1 AND status IN ('pending', 'running', 'needs_approval')
            """,
            UUID(graph_id),
        )
        await conn.execute(
            """
            UPDATE alpha_task_steps
            SET status = 'cancelled', updated_at = now()
            WHERE graph_id = $1 AND status IN ('pending', 'queued', 'running')
            """,
            UUID(graph_id),
        )
    return JSONResponse({"cancelled": True, "graph_id": graph_id})


# ------------------------------------------------------------------
# PENDING APPROVALS — for Approvals page
# ------------------------------------------------------------------


@tasks_router.get("/v1/tasks/pending-approvals")
async def pending_approvals(request: Request):
    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            """
            SELECT s.id AS step_id, s.step_name, s.step_type,
                   s.input, s.graph_id, s.content_tier,
                   g.title AS graph_title, g.user_type, g.priority,
                   s.created_at
            FROM alpha_task_steps s
            JOIN alpha_task_graphs g ON g.id = s.graph_id
            WHERE s.approval_required = true
              AND s.approval_status = 'pending'
              AND s.status = 'queued'
            ORDER BY g.priority DESC, s.created_at ASC
            """,
        )
    return JSONResponse(
        {
            "pending": [
                {
                    "step_id": str(r["step_id"]),
                    "step_name": r["step_name"],
                    "step_type": r["step_type"],
                    "input": r["input"],
                    "graph_id": str(r["graph_id"]),
                    "graph_title": r["graph_title"],
                    "content_tier": r["content_tier"],
                    "user_type": r["user_type"],
                    "priority": r["priority"],
                    "created_at": r["created_at"].isoformat(),
                }
                for r in rows
            ],
            "count": len(rows),
        }
    )
