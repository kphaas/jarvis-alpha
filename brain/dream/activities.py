"""Temporal activities for Dream Mode workflow.

Every activity takes idempotency_key as first arg for explicit discoverability.
Every DB-writing activity uses brain.dream._db.activity_db() for RLS-safe
connection acquisition.
"""

from __future__ import annotations

import json

from temporalio import activity

from brain.dream._db import activity_db
from brain.dream.briefing import build_dream_briefing
from brain.dream.planning import (
    get_registry,
    load_model_policy,
    plan_from_dict,
    plan_to_dict,
    policy_to_dict,
    review_to_dict,
)
from brain.dream.types import (
    CleanupSpec,
    PersistPlanResult,
    PersistPlanSpec,
    PlanSessionResult,
    PlanSessionSpec,
    ReviewPlanResult,
    ReviewPlanSpec,
)
from brain.services.planner import ClaudePlanner
from brain.services.reviewer import GeminiReviewer

_FINAL_STATUS_TITLE = {
    "completed": "Dream session completed",
    "halted": "Dream session halted (graceful)",
    "aborted": "Dream session aborted (fast halt)",
    "killed": "Dream session killed (emergency)",
    "failed": "Dream session failed",
}


@activity.defn(name="plan_session_activity")
async def plan_session_activity(
    idempotency_key: str,
    spec: PlanSessionSpec,
) -> PlanSessionResult:
    activity.logger.info(
        "plan_session_activity start idempotency_key=%s session_id=%s",
        idempotency_key,
        spec.session_id,
    )

    async with activity_db(user_id=spec.user_id) as conn:
        policy = await load_model_policy(conn, spec.goal_type)

    system_prompt = await get_registry().get("planner", version=spec.prompt_version)
    planner = ClaudePlanner(model=policy.planner_model, policy=policy)
    plan = await planner.plan(
        goal=spec.goal_text,
        system_prompt=system_prompt,
        recent_context=spec.recent_context,
        prior_lessons=spec.prior_lessons,
        revision_hint=spec.revision_hint,
    )
    return PlanSessionResult(plan=plan_to_dict(plan), policy=policy_to_dict(policy))


@activity.defn(name="review_plan_activity")
async def review_plan_activity(
    idempotency_key: str,
    spec: ReviewPlanSpec,
) -> ReviewPlanResult:
    activity.logger.info(
        "review_plan_activity start idempotency_key=%s session_id=%s",
        idempotency_key,
        spec.session_id,
    )

    async with activity_db(user_id=spec.user_id) as conn:
        policy = await load_model_policy(conn, spec.goal_type)

    plan = plan_from_dict(spec.plan)
    system_prompt = await get_registry().get("reviewer", version=spec.prompt_version)
    reviewer = GeminiReviewer(model=policy.reviewer_model, policy=policy)
    review = await reviewer.review(plan=plan, system_prompt=system_prompt)
    review_json = review_to_dict(review)
    return ReviewPlanResult(**review_json)


@activity.defn(name="persist_plan_activity")
async def persist_plan_activity(
    idempotency_key: str,
    spec: PersistPlanSpec,
) -> PersistPlanResult:
    activity.logger.info(
        "persist_plan_activity start idempotency_key=%s session_id=%s",
        idempotency_key,
        spec.session_id,
    )

    plan = plan_from_dict(spec.plan)
    review_issues = json.dumps(spec.review.get("issues", []))
    summary = (
        f"Dream plan approved with {len(plan.steps)} steps. "
        f"Reviewer verdict: {spec.review.get('verdict', 'UNKNOWN')}."
    )

    async with activity_db() as conn:
        await conn.execute(
            "DELETE FROM alpha_dream_steps WHERE session_id = $1",
            int(spec.session_id),
        )
        for step in plan.steps:
            await conn.execute(
                """
                INSERT INTO alpha_dream_steps (
                    session_id,
                    step_index,
                    name,
                    description,
                    depends_on,
                    agent_type,
                    max_retries
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                int(spec.session_id),
                step.step_index,
                step.name,
                step.description,
                step.depends_on,
                step.agent_type.value,
                3,
            )
        await conn.execute(
            """
            UPDATE alpha_dream_sessions
            SET step_count = $1,
                replan_count = $2,
                summary = $3,
                review_verdict = $4,
                review_reasoning = $5,
                review_issues = $6::jsonb
            WHERE id = $7
            """,
            len(plan.steps),
            spec.replan_count,
            summary,
            spec.review.get("verdict"),
            spec.review.get("reasoning"),
            review_issues,
            int(spec.session_id),
        )

    return PersistPlanResult(step_count=len(plan.steps))


@activity.defn(name="flush_cleanup_activity")
async def flush_cleanup_activity(
    idempotency_key: str,
    cleanup_spec: CleanupSpec,
) -> dict:
    activity.logger.info(
        "flush_cleanup_activity start idempotency_key=%s info=%s",
        idempotency_key,
        activity.info(),
    )

    completed_count = len(cleanup_spec.completed_steps)
    failed_count = len(cleanup_spec.failed_steps)
    final_status = cleanup_spec.final_status
    title = _FINAL_STATUS_TITLE.get(final_status, "Dream session update")

    if cleanup_spec.briefing_summary:
        body = cleanup_spec.briefing_summary
    else:
        body = (
            f"{completed_count} completed, {failed_count} failed. "
            f"Reason: {cleanup_spec.halt_reason or 'normal completion'}"
        )

    priority = 1 if final_status in {"killed", "aborted", "failed"} else 2
    payload = json.dumps(
        {
            "session_id": cleanup_spec.session_id,
            "final_status": cleanup_spec.final_status,
            "completed_steps": cleanup_spec.completed_steps,
            "failed_steps": cleanup_spec.failed_steps,
            "halt_reason": cleanup_spec.halt_reason,
            "halt_severity": cleanup_spec.halt_severity,
            "briefing_summary": cleanup_spec.briefing_summary,
            "idempotency_key": idempotency_key,
        }
    )

    briefing_row = None
    async with activity_db() as conn:
        await conn.execute(
            """
            UPDATE alpha_dream_sessions
            SET status = $1,
                kill_reason = $2,
                summary = $3,
                finished_at = now(),
                steps_completed = $4,
                steps_failed = $5
            WHERE id = $6
            """,
            final_status,
            cleanup_spec.halt_reason,
            cleanup_spec.briefing_summary,
            completed_count,
            failed_count,
            int(cleanup_spec.session_id),
        )

        session = await conn.fetchrow(
            "SELECT * FROM alpha_dream_sessions WHERE id = $1",
            int(cleanup_spec.session_id),
        )
        steps = await conn.fetch(
            """
            SELECT *
            FROM alpha_dream_steps
            WHERE session_id = $1
            ORDER BY step_index
            """,
            int(cleanup_spec.session_id),
        )
        if session:
            briefing = build_dream_briefing(
                dict(session),
                [dict(step) for step in steps],
            )
            briefing_row = await conn.fetchrow(
                """
                INSERT INTO alpha_briefings (
                    batch_run_id,
                    briefing_date,
                    started_at,
                    source,
                    summary,
                    results,
                    markdown
                )
                VALUES ($1, $2::date, $3, $4, $5::jsonb, $6::jsonb, $7)
                ON CONFLICT (batch_run_id) DO UPDATE
                SET briefing_date = EXCLUDED.briefing_date,
                    started_at = EXCLUDED.started_at,
                    source = EXCLUDED.source,
                    summary = EXCLUDED.summary,
                    results = EXCLUDED.results,
                    markdown = EXCLUDED.markdown
                RETURNING id, batch_run_id
                """,
                briefing["batch_run_id"],
                briefing["briefing_date"],
                briefing["started_at"],
                briefing["source"],
                json.dumps(briefing["summary"]),
                json.dumps(briefing["results"]),
                briefing["markdown"],
            )

        buddy_payload = json.loads(payload)
        if briefing_row:
            buddy_payload["briefing_id"] = briefing_row["id"]
            buddy_payload["briefing_batch_run_id"] = briefing_row["batch_run_id"]

        buddy_row = await conn.fetchrow(
            """
            INSERT INTO alpha_buddy_events (
                event_type,
                title,
                body,
                priority,
                source,
                payload
            )
            VALUES (
                'system',
                $1,
                $2,
                $3,
                'dream',
                $4::jsonb
            )
            RETURNING id
            """,
            title,
            body,
            priority,
            json.dumps(buddy_payload),
        )

    return {
        "session_status": final_status,
        "buddy_event_id": str(buddy_row["id"]),
        "briefing_id": briefing_row["id"] if briefing_row else None,
        "briefing_batch_run_id": briefing_row["batch_run_id"] if briefing_row else None,
    }
