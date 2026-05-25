from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from temporalio.exceptions import WorkflowAlreadyStartedError

from brain.db.pool import get_pool
from brain.db.rls import rls_connection
from brain.dream.client import (
    dream_workflow_id,
    signal_dream_session_halt,
    start_dream_session_workflow,
)
from brain.dream.health import read_worker_heartbeat, temporal_server_reachable
from brain.dream.read_only_executor import execute_read_only_step
from brain.dream.types import DreamSessionInput
from brain.middleware.scopes import check_scopes
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")
dream_router = APIRouter(prefix="/v1/dream", tags=["dream"])


class StepDefinition(BaseModel):
    step_index: int
    name: str
    description: Optional[str] = None
    depends_on: list[int] = Field(default_factory=list)
    agent_type: str  # llm, code, tool, cloud, canary
    max_retries: int = 3


class CreateSessionRequest(BaseModel):
    steps: list[StepDefinition] = Field(default_factory=list)
    goal_type: str = "default"
    goal_text: Optional[str] = None
    prompt_version: str = "v1"
    recent_context: Optional[str] = None
    prior_lessons: Optional[str] = None
    trigger: str = "manual"  # scheduled, manual, dry_run
    cost_budget_usd: float = 5.0
    max_duration_s: int = 14400  # 4 hours


class UpdateStepRequest(BaseModel):
    status: str
    model_used: Optional[str] = None
    input_hash: Optional[str] = None
    output_summary: Optional[str] = None
    verification: Optional[str] = None
    cost_usd: float = 0.0
    error_message: Optional[str] = None


class KillRequest(BaseModel):
    reason: str = "manual kill"


class ExecuteReadOnlyRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)


VALID_SESSION_TRANSITIONS = {
    "pending": ["running", "aborted"],
    "running": ["completed", "failed", "aborted", "killed"],
}

VALID_STEP_TRANSITIONS = {
    "pending": ["running", "blocked", "skipped"],
    "running": ["completed", "failed"],
    "failed": ["running"],  # retry
    "blocked": ["pending"],  # unblock if parent completes later (edge case)
}


async def _revert_temporal_start_reservation(
    pool,
    session_id: int,
    workflow_id: str,
) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
            await conn.execute(
                """
                UPDATE alpha_dream_sessions
                SET status = 'pending',
                    started_at = NULL,
                    temporal_workflow_id = NULL,
                    temporal_run_id = NULL
                WHERE id = $1
                  AND status = 'running'
                  AND temporal_workflow_id = $2
                  AND temporal_run_id IS NULL
                """,
                session_id,
                workflow_id,
            )


def _step_value(step, key: str, default=None):
    if hasattr(step, key):
        return getattr(step, key)
    try:
        return step[key]
    except (KeyError, TypeError):
        return default


def _goal_text_from_steps(steps) -> str:
    lines = ["Execute operator-defined Dream session steps:"]
    for step in steps:
        step_index = _step_value(step, "step_index")
        name = _step_value(step, "name")
        agent_type = _step_value(step, "agent_type")
        description = _step_value(step, "description", "") or ""
        lines.append(f"{step_index}. {name} [{agent_type}] {description}".strip())
    return "\n".join(lines)


@dream_router.post("/sessions")
async def create_session(request: Request, req: CreateSessionRequest):
    check_scopes(request, "dream.execute")
    if not req.goal_text and not req.steps:
        raise HTTPException(
            status_code=400,
            detail="Either goal_text or at least one step is required",
        )

    goal_text = req.goal_text or _goal_text_from_steps(req.steps)
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
            row = await conn.fetchrow(
                """
                INSERT INTO alpha_dream_sessions (
                    trigger,
                    cost_budget_usd,
                    max_duration_s,
                    step_count,
                    goal_type,
                    goal_text,
                    prompt_version,
                    recent_context,
                    prior_lessons
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id, status, created_at
                """,
                req.trigger,
                req.cost_budget_usd,
                req.max_duration_s,
                len(req.steps),
                req.goal_type,
                goal_text,
                req.prompt_version,
                req.recent_context,
                req.prior_lessons,
            )
            session_id = row["id"]
            for step in req.steps:
                await conn.execute(
                    """
                    INSERT INTO alpha_dream_steps
                        (session_id, step_index, name, description, depends_on, agent_type, max_retries)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    session_id,
                    step.step_index,
                    step.name,
                    step.description,
                    step.depends_on,
                    step.agent_type,
                    step.max_retries,
                )
    logger.info(
        "DREAM_SESSION_CREATED session_id=%d steps=%d trigger=%s",
        session_id,
        len(req.steps),
        req.trigger,
    )
    return {"session_id": session_id, "status": "pending", "step_count": len(req.steps)}


@dream_router.get("/sessions")
async def list_sessions(request: Request, limit: int = 20):
    async with rls_connection(request) as conn:
        rows = await conn.fetch(
            "SELECT * FROM alpha_dream_sessions ORDER BY created_at DESC LIMIT $1",
            min(limit, 100),
        )
    return [dict(r) for r in rows]


@dream_router.get("/sessions/{session_id}")
async def get_session(request: Request, session_id: int):
    async with rls_connection(request) as conn:
        session = await conn.fetchrow(
            "SELECT * FROM alpha_dream_sessions WHERE id = $1", session_id
        )
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        steps = await conn.fetch(
            "SELECT * FROM alpha_dream_steps WHERE session_id = $1 ORDER BY step_index",
            session_id,
        )
    return {"session": dict(session), "steps": [dict(s) for s in steps]}


@dream_router.get("/health")
async def dream_health(request: Request):
    check_scopes(request, "dream.execute")
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
            stale_rows = await conn.fetch(
                """
                SELECT id, status, temporal_workflow_id, temporal_run_id,
                       started_at, max_duration_s
                FROM alpha_dream_sessions
                WHERE status = 'running'
                  AND started_at IS NOT NULL
                  AND now() > started_at + (max_duration_s * interval '1 second')
                ORDER BY started_at
                LIMIT 20
                """
            )
    heartbeat = read_worker_heartbeat()
    temporal_reachable = await temporal_server_reachable()
    return {
        "status": "ok"
        if heartbeat["fresh"] and temporal_reachable and not stale_rows
        else "degraded",
        "worker_heartbeat": heartbeat,
        "temporal_server_reachable": temporal_reachable,
        "stale_running_sessions": [dict(row) for row in stale_rows],
    }


@dream_router.post("/sessions/{session_id}/start")
async def start_session(request: Request, session_id: int):
    check_scopes(request, "dream.execute")
    user_id = getattr(request.state, "user_id", "system")
    workflow_id = dream_workflow_id(session_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
            session = await conn.fetchrow(
                """
                SELECT id, status, trigger, goal_type, goal_text, prompt_version,
                       recent_context, prior_lessons
                FROM alpha_dream_sessions
                WHERE id = $1
                """,
                session_id,
            )
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            if session["status"] != "pending":
                raise HTTPException(
                    status_code=409,
                    detail=f"Cannot start session in '{session['status']}' state",
                )
            goal_text = session["goal_text"]
            if not goal_text:
                rows = await conn.fetch(
                    """
                    SELECT step_index, name, description, agent_type
                    FROM alpha_dream_steps
                    WHERE session_id = $1
                    ORDER BY step_index
                    """,
                    session_id,
                )
                goal_text = (
                    _goal_text_from_steps(rows)
                    if rows
                    else f"Dream session {session_id}"
                )
            await conn.execute(
                """
                UPDATE alpha_dream_sessions
                SET status = 'running',
                    started_at = $1,
                    temporal_workflow_id = $2
                WHERE id = $3
                """,
                datetime.now(timezone.utc),
                workflow_id,
                session_id,
            )

    workflow_input = DreamSessionInput(
        session_id=str(session_id),
        user_id=user_id,
        prompt=goal_text,
        trigger=session["trigger"],
        goal_type=session["goal_type"] or "default",
        prompt_version=session["prompt_version"] or "v1",
        recent_context=session["recent_context"],
        prior_lessons=session["prior_lessons"],
    )
    try:
        started = await start_dream_session_workflow(workflow_input)
    except WorkflowAlreadyStartedError as e:
        await _revert_temporal_start_reservation(pool, session_id, workflow_id)
        raise HTTPException(
            status_code=409,
            detail=f"Dream workflow already exists for session {session_id}",
        ) from e
    except Exception as e:
        await _revert_temporal_start_reservation(pool, session_id, workflow_id)
        logger.error(
            "DREAM_TEMPORAL_START_FAILED session_id=%d error=%s", session_id, e
        )
        raise HTTPException(
            status_code=503,
            detail="Temporal workflow start failed",
        ) from e

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
            await conn.execute(
                """
                UPDATE alpha_dream_sessions
                SET temporal_run_id = $1
                WHERE id = $2 AND temporal_workflow_id = $3
                """,
                started.run_id,
                session_id,
                started.workflow_id,
            )

    logger.info(
        "DREAM_SESSION_STARTED session_id=%d workflow_id=%s run_id=%s",
        session_id,
        started.workflow_id,
        started.run_id,
    )
    return {
        "session_id": session_id,
        "status": "running",
        "temporal_workflow_id": started.workflow_id,
        "temporal_run_id": started.run_id,
    }


@dream_router.post("/sessions/{session_id}/kill")
async def kill_session(request: Request, session_id: int, req: KillRequest):
    check_scopes(request, "dream.execute", "dream.kill")
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
            session = await conn.fetchrow(
                """
                SELECT id, status, temporal_workflow_id, temporal_run_id
                FROM alpha_dream_sessions
                WHERE id = $1
                """,
                session_id,
            )
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            if session["status"] not in ("pending", "running"):
                raise HTTPException(
                    status_code=409,
                    detail=f"Session already in terminal state '{session['status']}'",
                )
            signal_status = "not_applicable"
            if session["status"] == "running" and session["temporal_workflow_id"]:
                try:
                    await signal_dream_session_halt(
                        session["temporal_workflow_id"],
                        run_id=session["temporal_run_id"],
                        reason=req.reason,
                        severity="killed",
                    )
                    signal_status = "sent"
                except Exception as e:
                    logger.error(
                        "DREAM_TEMPORAL_HALT_SIGNAL_FAILED session_id=%d error=%s",
                        session_id,
                        e,
                    )
                    raise HTTPException(
                        status_code=503,
                        detail="Temporal halt signal failed",
                    ) from e
            await conn.execute(
                """
                UPDATE alpha_dream_sessions
                SET status = 'killed', finished_at = $1, kill_reason = $2
                WHERE id = $3
                """,
                datetime.now(timezone.utc),
                req.reason,
                session_id,
            )
            await conn.execute(
                """
                UPDATE alpha_dream_steps
                SET status = 'blocked', error_message = 'Session killed: ' || $1
                WHERE session_id = $2 AND status IN ('pending', 'running')
                """,
                req.reason,
                session_id,
            )
    logger.warning(
        "DREAM_SESSION_KILLED session_id=%d reason=%s", session_id, req.reason
    )
    return {
        "session_id": session_id,
        "status": "killed",
        "reason": req.reason,
        "temporal_signal": signal_status,
    }


@dream_router.get("/sessions/{session_id}/next-step")
async def get_next_step(request: Request, session_id: int):
    check_scopes(request, "dream.execute")
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
            session = await conn.fetchrow(
                "SELECT id, status, cost_actual_usd, cost_budget_usd FROM alpha_dream_sessions WHERE id = $1",
                session_id,
            )
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            if session["status"] != "running":
                return {"next_step": None, "reason": f"session is {session['status']}"}

            if session["cost_actual_usd"] >= session["cost_budget_usd"]:
                return {"next_step": None, "reason": "cost budget exceeded"}

            pending_steps = await conn.fetch(
                """
                SELECT * FROM alpha_dream_steps
                WHERE session_id = $1 AND status = 'pending'
                ORDER BY step_index
                """,
                session_id,
            )
            for step in pending_steps:
                deps = step["depends_on"] or []
                if not deps:
                    return {"next_step": dict(step)}
                dep_statuses = await conn.fetch(
                    """
                    SELECT step_index, status FROM alpha_dream_steps
                    WHERE session_id = $1 AND step_index = ANY($2)
                    """,
                    session_id,
                    deps,
                )
                all_completed = all(d["status"] == "completed" for d in dep_statuses)
                any_failed = any(
                    d["status"] in ("failed", "blocked") for d in dep_statuses
                )
                if any_failed:
                    await conn.execute(
                        """
                        UPDATE alpha_dream_steps SET status = 'blocked',
                        error_message = 'Dependency failed or blocked'
                        WHERE id = $1
                        """,
                        step["id"],
                    )
                    await conn.execute(
                        "UPDATE alpha_dream_sessions SET steps_blocked = steps_blocked + 1 WHERE id = $1",
                        session_id,
                    )
                    continue
                if all_completed:
                    return {"next_step": dict(step)}

    return {"next_step": None, "reason": "no runnable steps"}


@dream_router.post("/sessions/{session_id}/execute-readonly")
async def execute_readonly_session(
    request: Request,
    session_id: int,
    req: ExecuteReadOnlyRequest,
):
    check_scopes(request, "dream.execute")
    pool = get_pool()
    now = datetime.now(timezone.utc)
    executed = []
    skipped = []

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
            session = await conn.fetchrow(
                """
                SELECT id, status, review_verdict
                FROM alpha_dream_sessions
                WHERE id = $1
                """,
                session_id,
            )
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            if session["status"] not in ("completed", "running"):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Read-only execution requires a completed approved plan "
                        f"or running session, got '{session['status']}'"
                    ),
                )
            if session["review_verdict"] not in (None, "APPROVED"):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Cannot execute plan with "
                        f"review_verdict={session['review_verdict']}"
                    ),
                )

            steps = await conn.fetch(
                """
                SELECT *
                FROM alpha_dream_steps
                WHERE session_id = $1
                ORDER BY step_index
                """,
                session_id,
            )
            status_by_index = {step["step_index"]: step["status"] for step in steps}

            for step in steps:
                if len(executed) >= req.limit:
                    break
                if step["status"] != "pending":
                    continue
                deps = step["depends_on"] or []
                unmet = [
                    dep
                    for dep in deps
                    if status_by_index.get(dep) not in ("completed", "skipped")
                ]
                if unmet:
                    skipped.append(
                        {
                            "step_id": step["id"],
                            "step_index": step["step_index"],
                            "name": step["name"],
                            "reason": f"dependencies_not_complete:{unmet}",
                        }
                    )
                    continue

                result = execute_read_only_step(dict(step))
                if result.status != "completed":
                    skipped.append(
                        {
                            "step_id": step["id"],
                            "step_index": step["step_index"],
                            "name": step["name"],
                            "reason": result.reason,
                        }
                    )
                    continue

                await conn.execute(
                    """
                    UPDATE alpha_dream_steps
                    SET status = 'running', started_at = $1
                    WHERE id = $2 AND status = 'pending'
                    """,
                    now,
                    step["id"],
                )
                await conn.execute(
                    """
                    UPDATE alpha_dream_steps
                    SET status = 'completed',
                        finished_at = $1,
                        input_hash = $2,
                        output_summary = $3,
                        verification = $4,
                        cost_usd = 0
                    WHERE id = $5
                    """,
                    now,
                    result.input_hash,
                    result.output_summary,
                    result.verification,
                    step["id"],
                )
                status_by_index[step["step_index"]] = "completed"
                executed.append(
                    {
                        "step_id": step["id"],
                        "step_index": step["step_index"],
                        "name": step["name"],
                        "verification": result.verification,
                    }
                )

            counts = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                    COUNT(*) FILTER (WHERE status = 'blocked') AS blocked,
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending
                FROM alpha_dream_steps
                WHERE session_id = $1
                """,
                session_id,
            )
            await conn.execute(
                """
                UPDATE alpha_dream_sessions
                SET steps_completed = $1,
                    steps_failed = $2,
                    steps_blocked = $3
                WHERE id = $4
                """,
                counts["completed"],
                counts["failed"],
                counts["blocked"],
                session_id,
            )

    logger.info(
        "DREAM_READONLY_EXECUTION session_id=%d executed=%d skipped=%d",
        session_id,
        len(executed),
        len(skipped),
    )
    return {
        "session_id": session_id,
        "executed": executed,
        "skipped": skipped,
        "remaining_pending": counts["pending"],
    }


@dream_router.patch("/steps/{step_id}")
async def update_step(request: Request, step_id: int, req: UpdateStepRequest):
    check_scopes(request, "dream.execute")
    pool = get_pool()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
            step = await conn.fetchrow(
                "SELECT * FROM alpha_dream_steps WHERE id = $1", step_id
            )
            if not step:
                raise HTTPException(status_code=404, detail="Step not found")

            current = step["status"]
            target = req.status
            valid = VALID_STEP_TRANSITIONS.get(current, [])
            if target not in valid:
                raise HTTPException(
                    status_code=409, detail=f"Invalid transition: {current} → {target}"
                )

            if target == "running":
                await conn.execute(
                    "UPDATE alpha_dream_steps SET status = 'running', started_at = $1 WHERE id = $2",
                    now,
                    step_id,
                )
            elif target == "completed":
                await conn.execute(
                    """
                    UPDATE alpha_dream_steps
                    SET status = 'completed', finished_at = $1, model_used = $2,
                        input_hash = $3, output_summary = $4, verification = $5,
                        cost_usd = $6
                    WHERE id = $7
                    """,
                    now,
                    req.model_used,
                    req.input_hash,
                    req.output_summary,
                    req.verification,
                    req.cost_usd,
                    step_id,
                )
                await conn.execute(
                    """
                    UPDATE alpha_dream_sessions
                    SET steps_completed = steps_completed + 1,
                        cost_actual_usd = cost_actual_usd + $1
                    WHERE id = $2
                    """,
                    req.cost_usd,
                    step["session_id"],
                )
            elif target == "failed":
                retry = step["retry_count"] + 1
                await conn.execute(
                    """
                    UPDATE alpha_dream_steps
                    SET status = 'failed', finished_at = $1, error_message = $2,
                        retry_count = $3, cost_usd = cost_usd + $4
                    WHERE id = $5
                    """,
                    now,
                    req.error_message,
                    retry,
                    req.cost_usd,
                    step_id,
                )
                await conn.execute(
                    "UPDATE alpha_dream_sessions SET cost_actual_usd = cost_actual_usd + $1 WHERE id = $2",
                    req.cost_usd,
                    step["session_id"],
                )
                if retry >= step["max_retries"]:
                    await conn.execute(
                        "UPDATE alpha_dream_sessions SET steps_failed = steps_failed + 1 WHERE id = $1",
                        step["session_id"],
                    )
            elif target == "blocked":
                await conn.execute(
                    "UPDATE alpha_dream_steps SET status = 'blocked', error_message = $1 WHERE id = $2",
                    req.error_message,
                    step_id,
                )
                await conn.execute(
                    "UPDATE alpha_dream_sessions SET steps_blocked = steps_blocked + 1 WHERE id = $1",
                    step["session_id"],
                )

    logger.info(
        "DREAM_STEP_UPDATE step_id=%d transition=%s→%s", step_id, current, target
    )
    return {"step_id": step_id, "status": target}


@dream_router.post("/sessions/{session_id}/complete")
async def complete_session(request: Request, session_id: int):
    check_scopes(request, "dream.execute")
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
            session = await conn.fetchrow(
                "SELECT * FROM alpha_dream_sessions WHERE id = $1", session_id
            )
            if not session:
                raise HTTPException(status_code=404, detail="Session not found")
            if session["status"] != "running":
                raise HTTPException(
                    status_code=409, detail=f"Session is {session['status']}"
                )

            steps = await conn.fetch(
                "SELECT status FROM alpha_dream_steps WHERE session_id = $1",
                session_id,
            )
            any_failed = any(s["status"] in ("failed", "blocked") for s in steps)
            final_status = "failed" if any_failed else "completed"

            summary_parts = []
            for s in ("completed", "failed", "blocked", "skipped", "pending"):
                count = sum(1 for st in steps if st["status"] == s)
                if count:
                    summary_parts.append(f"{s}:{count}")

            await conn.execute(
                """
                UPDATE alpha_dream_sessions
                SET status = $1, finished_at = $2, summary = $3
                WHERE id = $4
                """,
                final_status,
                datetime.now(timezone.utc),
                " | ".join(summary_parts),
                session_id,
            )
    logger.info(
        "DREAM_SESSION_COMPLETE session_id=%d status=%s", session_id, final_status
    )
    return {
        "session_id": session_id,
        "status": final_status,
        "summary": " | ".join(summary_parts),
    }
