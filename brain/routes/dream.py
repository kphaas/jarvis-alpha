from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from brain.db.pool import get_pool
from brain.middleware.scopes import require_scopes
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
    steps: list[StepDefinition]
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


@dream_router.post("/sessions")
@require_scopes("dream.execute")
async def create_session(request: Request, req: CreateSessionRequest):
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO alpha_dream_sessions (trigger, cost_budget_usd, max_duration_s, step_count)
                VALUES ($1, $2, $3, $4)
                RETURNING id, status, created_at
                """,
                req.trigger,
                req.cost_budget_usd,
                req.max_duration_s,
                len(req.steps),
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
async def list_sessions(limit: int = 20):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM alpha_dream_sessions ORDER BY created_at DESC LIMIT $1",
            min(limit, 100),
        )
    return [dict(r) for r in rows]


@dream_router.get("/sessions/{session_id}")
async def get_session(session_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
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


@dream_router.post("/sessions/{session_id}/start")
@require_scopes("dream.execute")
async def start_session(request: Request, session_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
        session = await conn.fetchrow(
            "SELECT id, status FROM alpha_dream_sessions WHERE id = $1", session_id
        )
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if session["status"] != "pending":
            raise HTTPException(
                status_code=409,
                detail=f"Cannot start session in '{session['status']}' state",
            )
        await conn.execute(
            """
            UPDATE alpha_dream_sessions
            SET status = 'running', started_at = $1
            WHERE id = $2
            """,
            datetime.now(timezone.utc),
            session_id,
        )
    logger.info("DREAM_SESSION_STARTED session_id=%d", session_id)
    return {"session_id": session_id, "status": "running"}


@dream_router.post("/sessions/{session_id}/kill")
@require_scopes("dream.execute", "dream.kill")
async def kill_session(request: Request, session_id: int, req: KillRequest):
    pool = get_pool()
    async with pool.acquire() as conn:
        session = await conn.fetchrow(
            "SELECT id, status FROM alpha_dream_sessions WHERE id = $1", session_id
        )
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        if session["status"] not in ("pending", "running"):
            raise HTTPException(
                status_code=409,
                detail=f"Session already in terminal state '{session['status']}'",
            )
        async with conn.transaction():
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
    return {"session_id": session_id, "status": "killed", "reason": req.reason}


@dream_router.get("/sessions/{session_id}/next-step")
@require_scopes("dream.execute")
async def get_next_step(request: Request, session_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
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
            any_failed = any(d["status"] in ("failed", "blocked") for d in dep_statuses)
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


@dream_router.patch("/steps/{step_id}")
@require_scopes("dream.execute")
async def update_step(request: Request, step_id: int, req: UpdateStepRequest):
    pool = get_pool()
    now = datetime.now(timezone.utc)
    async with pool.acquire() as conn:
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

        async with conn.transaction():
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
@require_scopes("dream.execute")
async def complete_session(request: Request, session_id: int):
    pool = get_pool()
    async with pool.acquire() as conn:
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
            "SELECT status FROM alpha_dream_steps WHERE session_id = $1", session_id
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
