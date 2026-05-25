from datetime import datetime, timezone
from decimal import Decimal

from brain.dream.briefing import DREAM_BRIEFING_SOURCE, build_dream_briefing


def test_build_dream_briefing_matches_alpha_briefing_shape():
    session = {
        "id": 42,
        "status": "completed",
        "started_at": datetime(2026, 5, 25, 5, 0, tzinfo=timezone.utc),
        "finished_at": datetime(2026, 5, 25, 5, 5, tzinfo=timezone.utc),
        "created_at": datetime(2026, 5, 25, 4, 59, tzinfo=timezone.utc),
        "cost_budget_usd": Decimal("5.0000"),
        "cost_actual_usd": Decimal("0.2500"),
        "review_verdict": "APPROVED",
        "summary": "Dream workflow completed.",
        "temporal_run_id": "run-1",
    }
    steps = [
        {
            "step_index": 1,
            "status": "completed",
            "name": "inspect_worker",
            "agent_type": "tool",
            "retry_count": 0,
            "max_retries": 3,
            "cost_usd": Decimal("0"),
        },
        {
            "step_index": 2,
            "status": "blocked",
            "name": "write_report",
            "agent_type": "tool",
            "retry_count": 0,
            "max_retries": 3,
            "cost_usd": Decimal("0.25"),
            "error_message": "Approval required",
        },
    ]

    briefing = build_dream_briefing(session, steps)

    assert briefing["source"] == DREAM_BRIEFING_SOURCE
    assert briefing["batch_run_id"].startswith("20260525_0500_")
    assert briefing["summary"]["pass"] == 1
    assert briefing["summary"]["fail"] == 1
    assert briefing["summary"]["skip"] == 0
    assert briefing["summary"]["total_cost_usd"] == 0.25
    assert briefing["results"][0]["feature_id"] == "dream_step_1"
    assert "Dream Morning Briefing" in briefing["markdown"]
