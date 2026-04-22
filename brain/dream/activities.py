"""Temporal activities for Dream Mode workflow.

D3.3 scope: flush_cleanup_activity.
D3.3 scope remainder: plan_activity, review_activity (added in 4b-iii).
Cost recording is handled by Gateway's cost_emitter — no Brain-side cost
activity needed. step_execute deferred to D3.4.

Every activity takes idempotency_key as first arg for explicit discoverability.
Every DB-writing activity uses brain.dream._db.activity_db() for RLS-safe
connection acquisition.
"""

from __future__ import annotations

import json

from temporalio import activity

from brain.dream._db import activity_db
from brain.dream.types import CleanupSpec

_FINAL_STATUS_TITLE = {
    "completed": "Dream session completed",
    "halted": "Dream session halted (graceful)",
    "aborted": "Dream session aborted (fast halt)",
    "killed": "Dream session killed (emergency)",
    "failed": "Dream session failed",
}


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
            payload,
        )

    return {
        "session_status": final_status,
        "buddy_event_id": str(buddy_row["id"]),
    }
