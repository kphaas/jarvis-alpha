from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from brain.dream.write_executor import (
    PUBLISH_BRIEFING_HANDLER,
    decode_write_execution_verification,
    execute_approved_write_step,
    write_handler_for_step,
)


class FakeConn:
    def __init__(self, verification_matches: bool = True):
        self.verification_matches = verification_matches
        self.briefing = None
        self.executed = []

    async def fetchrow(self, query, *args):
        if "briefing_date" in query and "FROM alpha_briefings" in query:
            return None
        if "INSERT INTO alpha_briefings" in query:
            self.briefing = {
                "id": 44,
                "batch_run_id": args[0],
                "source": args[3],
                "summary": json.loads(args[4]),
                "results": json.loads(args[5]),
                "markdown": args[6],
            }
            return {"id": 44, "batch_run_id": args[0]}
        if "SELECT id, batch_run_id, source, markdown" in query:
            if not self.briefing:
                return None
            return {
                "id": self.briefing["id"],
                "batch_run_id": self.briefing["batch_run_id"],
                "source": self.briefing["source"],
                "markdown": (
                    self.briefing["markdown"]
                    if self.verification_matches
                    else "tampered markdown"
                ),
            }
        raise AssertionError(f"unexpected fetchrow query: {query}")

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "DELETE 1"


def _session():
    now = datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc)
    return {
        "id": 10,
        "status": "running",
        "created_at": now,
        "started_at": now,
        "finished_at": None,
        "cost_budget_usd": 5,
        "cost_actual_usd": 0,
        "review_verdict": "APPROVED",
        "summary": None,
        "temporal_run_id": "run-10",
    }


def _step():
    return {
        "id": 2,
        "session_id": 10,
        "step_index": 2,
        "name": "update_briefing_row",
        "description": "Write the generated morning briefing row.",
        "agent_type": "tool",
        "depends_on": [],
        "status": "blocked",
        "cost_usd": 0,
        "retry_count": 0,
        "max_retries": 3,
        "error_message": None,
        "verification": "dream_write_gate_v1:{}",
    }


def test_write_handler_allows_only_dream_owned_briefing_write():
    assert write_handler_for_step(_step()) == PUBLISH_BRIEFING_HANDLER
    assert (
        write_handler_for_step(
            {
                **_step(),
                "name": "restart_launchagent",
                "description": "Restart the Brain service.",
            }
        )
        is None
    )


@pytest.mark.asyncio
async def test_execute_approved_write_step_publishes_and_verifies_briefing():
    conn = FakeConn()
    step = _step()

    result = await execute_approved_write_step(
        conn,
        _session(),
        [step],
        step,
        {"queue_id": "queue-id", "risk_tier": "T4"},
    )

    assert result.status == "completed"
    assert result.reason == "published_dream_briefing_verified"
    assert result.input_hash
    payload = decode_write_execution_verification(result.verification)
    assert payload["handler"] == PUBLISH_BRIEFING_HANDLER
    assert payload["approval"]["queue_id"] == "queue-id"
    assert payload["post_action_verification"]["passed"] is True
    assert payload["compensation"]["had_existing"] is False
    assert payload["compensation"]["ran"] is False
    assert conn.briefing["source"] == "dream_mode"


@pytest.mark.asyncio
async def test_execute_approved_write_step_runs_compensation_on_failed_verification():
    conn = FakeConn(verification_matches=False)
    step = _step()

    result = await execute_approved_write_step(conn, _session(), [step], step)

    assert result.status == "failed"
    payload = decode_write_execution_verification(result.verification)
    assert payload["post_action_verification"]["passed"] is False
    assert payload["compensation"]["ran"] is True
    assert any("DELETE FROM alpha_briefings" in query for query, _ in conn.executed)
