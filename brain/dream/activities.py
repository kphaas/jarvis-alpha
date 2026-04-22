"""Temporal activities for Dream Mode workflow.

D3.3 scope: record_cost_activity, flush_cleanup_activity.
D3.3 scope remainder: plan_activity, review_activity, step_execute_activity
(added in prompt 4b after these pass smoke).

Every activity takes idempotency_key as first arg for explicit discoverability.
Every DB-writing activity uses brain.dream._db.activity_db() for RLS-safe
connection acquisition.
"""

from __future__ import annotations

import json

from temporalio import activity

from brain.dream._db import activity_db
from brain.dream.types import CleanupSpec, CostRecord

_FINAL_STATUS_TITLE = {
    "completed": "Dream session completed",
    "halted": "Dream session halted (graceful)",
    "aborted": "Dream session aborted (fast halt)",
    "killed": "Dream session killed (emergency)",
    "failed": "Dream session failed",
}


@activity.defn(name="record_cost_activity")
async def record_cost_activity(
    idempotency_key: str,
    cost_record: CostRecord,
) -> dict:
    activity.logger.info(
        "record_cost_activity start idempotency_key=%s info=%s",
        idempotency_key,
        activity.info(),
    )

    async with activity_db(user_id=cost_record.on_behalf_of) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO alpha_cloud_costs (
                provider,
                model,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                cost_usd,
                session_type,
                key_name,
                intent,
                executor,
                on_behalf_of,
                source_request_id,
                idempotency_key
            )
            VALUES (
                $1,
                $2,
                $3,
                $4,
                $5,
                $6,
                'dream',
                NULL,
                NULL,
                'dream',
                $7,
                NULL,
                $8
            )
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING id
            """,
            cost_record.provider,
            cost_record.model,
            cost_record.prompt_tokens,
            cost_record.completion_tokens,
            cost_record.total_tokens,
            cost_record.cost_usd,
            cost_record.on_behalf_of,
            idempotency_key,
        )

    inserted = row is not None
    return {
        "inserted": inserted,
        "row_id": str(row["id"]) if inserted else None,
        "idempotency_key": idempotency_key,
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
            WHERE id = CAST($6 AS bigint)
            """,
            final_status,
            cleanup_spec.halt_reason,
            cleanup_spec.briefing_summary,
            completed_count,
            failed_count,
            cleanup_spec.session_id,
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
