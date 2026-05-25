"""Approval-consumed write execution helpers for Dream Mode.

The executor is intentionally narrow: it only runs named, deterministic,
Dream-owned writes after an approval row has been validated by the route.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from brain.dream.briefing import DREAM_BRIEFING_SOURCE, build_dream_briefing

EXECUTION_VERIFICATION_PREFIX = "dream_write_exec_v1:"
PUBLISH_BRIEFING_HANDLER = "publish_dream_briefing"

_BRIEFING_TERMS = ("briefing", "morning briefing")
_PUBLISH_TERMS = ("create", "publish", "upsert", "update", "write")


@dataclass(frozen=True)
class DreamWriteExecutionResult:
    status: Literal["completed", "failed", "skipped"]
    reason: str
    output_summary: str | None = None
    verification: str | None = None
    input_hash: str | None = None
    side_effect: dict[str, Any] | None = None
    compensation: dict[str, Any] | None = None


def _step_text(step: Mapping[str, Any]) -> str:
    return " ".join(str(step.get(key) or "") for key in ("name", "description"))


def write_handler_for_step(step: Mapping[str, Any]) -> str | None:
    """Return the allowlisted write handler for a Dream step, if any."""
    agent_type = step.get("agent_type")
    if agent_type not in {"tool", "canary"}:
        return None

    text = _step_text(step).lower().replace("_", " ")
    if any(term in text for term in _BRIEFING_TERMS) and any(
        term in text for term in _PUBLISH_TERMS
    ):
        return PUBLISH_BRIEFING_HANDLER
    return None


def _json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, default=str)


def _hash_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _input_hash(step: Mapping[str, Any], handler: str) -> str:
    return _hash_payload(
        {
            "handler": handler,
            "session_id": step.get("session_id"),
            "step_id": step.get("id"),
            "step_index": step.get("step_index"),
            "name": step.get("name"),
            "description": step.get("description"),
        }
    )[:16]


def _briefing_hash(briefing: Mapping[str, Any]) -> str:
    return _hash_payload(
        {
            "batch_run_id": briefing.get("batch_run_id"),
            "summary": briefing.get("summary"),
            "results": briefing.get("results"),
            "markdown": briefing.get("markdown"),
        }
    )


def _project_completed_steps(
    steps: Sequence[Mapping[str, Any]],
    completed_step_id: int,
    output_summary: str,
) -> list[dict[str, Any]]:
    projected = []
    for step in steps:
        row = dict(step)
        if row.get("id") == completed_step_id:
            row["status"] = "completed"
            row["error_message"] = None
            row["output_summary"] = output_summary
            row["cost_usd"] = 0
        projected.append(row)
    return projected


async def _capture_previous_briefing(conn, batch_run_id: str) -> dict[str, Any]:
    row = await conn.fetchrow(
        """
        SELECT id, batch_run_id, briefing_date, started_at, source,
               summary, results, markdown
        FROM alpha_briefings
        WHERE batch_run_id = $1
        FOR UPDATE
        """,
        batch_run_id,
    )
    if not row:
        return {
            "handler": PUBLISH_BRIEFING_HANDLER,
            "batch_run_id": batch_run_id,
            "had_existing": False,
        }

    return {
        "handler": PUBLISH_BRIEFING_HANDLER,
        "batch_run_id": batch_run_id,
        "had_existing": True,
        "previous": {
            "id": row["id"],
            "batch_run_id": row["batch_run_id"],
            "briefing_date": str(row["briefing_date"]),
            "started_at": str(row["started_at"]),
            "source": row["source"],
            "summary": _json_text(row["summary"]),
            "results": _json_text(row["results"]),
            "markdown": row["markdown"],
        },
    }


async def compensate_write_execution(conn, compensation: Mapping[str, Any]) -> bool:
    """Run compensation for a failed allowlisted Dream write."""
    if compensation.get("handler") != PUBLISH_BRIEFING_HANDLER:
        return False

    batch_run_id = str(compensation["batch_run_id"])
    if compensation.get("had_existing"):
        previous = compensation["previous"]
        await conn.execute(
            """
            UPDATE alpha_briefings
            SET briefing_date = $2::date,
                started_at = $3::timestamptz,
                source = $4,
                summary = $5::jsonb,
                results = $6::jsonb,
                markdown = $7
            WHERE batch_run_id = $1
            """,
            batch_run_id,
            previous["briefing_date"],
            previous["started_at"],
            previous["source"],
            previous["summary"],
            previous["results"],
            previous["markdown"],
        )
        return True

    await conn.execute(
        """
        DELETE FROM alpha_briefings
        WHERE batch_run_id = $1 AND source = $2
        """,
        batch_run_id,
        DREAM_BRIEFING_SOURCE,
    )
    return True


def encode_write_execution_verification(payload: Mapping[str, Any]) -> str:
    return EXECUTION_VERIFICATION_PREFIX + json.dumps(
        payload,
        sort_keys=True,
        default=str,
    )


def decode_write_execution_verification(value: object) -> dict[str, Any] | None:
    if not isinstance(value, str) or not value.startswith(
        EXECUTION_VERIFICATION_PREFIX
    ):
        return None
    try:
        return json.loads(value[len(EXECUTION_VERIFICATION_PREFIX) :])
    except json.JSONDecodeError:
        return None


async def _execute_publish_dream_briefing(
    conn,
    session: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
    step: Mapping[str, Any],
    approval_context: Mapping[str, Any] | None,
) -> DreamWriteExecutionResult:
    step_id = int(step["id"])
    output_summary = "Published Dream morning briefing to alpha_briefings."
    projected_steps = _project_completed_steps(steps, step_id, output_summary)
    briefing = build_dream_briefing(dict(session), projected_steps)
    compensation = await _capture_previous_briefing(conn, briefing["batch_run_id"])
    expected_hash = _briefing_hash(briefing)

    write_args = (
        briefing["batch_run_id"],
        briefing["briefing_date"],
        briefing["started_at"],
        briefing["source"],
        json.dumps(briefing["summary"]),
        json.dumps(briefing["results"]),
        briefing["markdown"],
    )
    if compensation["had_existing"]:
        row = await conn.fetchrow(
            """
            UPDATE alpha_briefings
            SET briefing_date = $2::date,
                started_at = $3,
                source = $4,
                summary = $5::jsonb,
                results = $6::jsonb,
                markdown = $7
            WHERE batch_run_id = $1
            RETURNING id, batch_run_id
            """,
            *write_args,
        )
    else:
        row = await conn.fetchrow(
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
            ON CONFLICT (batch_run_id) DO NOTHING
            RETURNING id, batch_run_id
            """,
            *write_args,
        )
        if not row:
            compensation = await _capture_previous_briefing(
                conn, briefing["batch_run_id"]
            )
            row = await conn.fetchrow(
                """
                UPDATE alpha_briefings
                SET briefing_date = $2::date,
                    started_at = $3,
                    source = $4,
                    summary = $5::jsonb,
                    results = $6::jsonb,
                    markdown = $7
                WHERE batch_run_id = $1
                RETURNING id, batch_run_id
                """,
                *write_args,
            )
    observed = await conn.fetchrow(
        """
        SELECT id, batch_run_id, source, markdown
        FROM alpha_briefings
        WHERE batch_run_id = $1
        """,
        briefing["batch_run_id"],
    )
    verification_passed = bool(
        observed
        and observed["id"] == row["id"]
        and observed["source"] == DREAM_BRIEFING_SOURCE
        and observed["markdown"] == briefing["markdown"]
    )
    compensation_ran = False
    if not verification_passed:
        compensation_ran = await compensate_write_execution(conn, compensation)

    payload = {
        "handler": PUBLISH_BRIEFING_HANDLER,
        "approval": dict(approval_context or {}),
        "side_effect": {
            "table": "alpha_briefings",
            "briefing_id": row["id"],
            "batch_run_id": row["batch_run_id"],
            "expected_hash": expected_hash,
        },
        "post_action_verification": {
            "passed": verification_passed,
            "checks": ["row_exists", "source_matches", "markdown_matches"],
        },
        "compensation": {
            **compensation,
            "ran": compensation_ran,
        },
    }
    verification = encode_write_execution_verification(payload)
    if not verification_passed:
        return DreamWriteExecutionResult(
            status="failed",
            reason="post_action_verification_failed",
            output_summary="Dream briefing write failed verification; compensation ran.",
            verification=verification,
            input_hash=_input_hash(step, PUBLISH_BRIEFING_HANDLER),
            side_effect=payload["side_effect"],
            compensation=payload["compensation"],
        )

    return DreamWriteExecutionResult(
        status="completed",
        reason="published_dream_briefing_verified",
        output_summary=output_summary,
        verification=verification,
        input_hash=_input_hash(step, PUBLISH_BRIEFING_HANDLER),
        side_effect=payload["side_effect"],
        compensation=payload["compensation"],
    )


async def execute_approved_write_step(
    conn,
    session: Mapping[str, Any],
    steps: Sequence[Mapping[str, Any]],
    step: Mapping[str, Any],
    approval_context: Mapping[str, Any] | None = None,
) -> DreamWriteExecutionResult:
    """Execute an already-approved Dream write step if it is allowlisted."""
    handler = write_handler_for_step(step)
    if handler != PUBLISH_BRIEFING_HANDLER:
        return DreamWriteExecutionResult(
            status="skipped",
            reason="write_handler_not_allowlisted",
        )
    return await _execute_publish_dream_briefing(
        conn,
        session,
        steps,
        step,
        approval_context,
    )
