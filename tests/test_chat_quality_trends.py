from __future__ import annotations

import json

from brain.services.chat_quality_trends import (
    CHAT_QUALITY_TREND_SCHEMA_VERSION,
    append_chat_quality_trend_snapshot,
    chat_quality_trend_snapshot,
    load_chat_quality_trend_history,
    summarize_chat_quality_trend,
)


def test_chat_quality_trend_detects_regressed_groups() -> None:
    old = _payload(
        passed=18,
        failed=0,
        groups={"quality_gateway": 0, "trace_replay": 0},
        elapsed_ms=20,
        accept_rate=0.8,
        escalation_rate=0.1,
    )
    current = _payload(
        passed=17,
        failed=1,
        groups={"quality_gateway": 1, "trace_replay": 0},
        elapsed_ms=35,
        accept_rate=0.6,
        escalation_rate=0.3,
    )

    trend = summarize_chat_quality_trend(current, [old])

    assert trend == {
        "schema_version": CHAT_QUALITY_TREND_SCHEMA_VERSION,
        "window_runs": 2,
        "passed_runs": 1,
        "failed_runs": 1,
        "pass_rate_percent": 50,
        "latest_status": "failed",
        "latest_passed": 17,
        "latest_failed": 1,
        "failed_delta": 1,
        "passed_delta": -1,
        "case_count_delta": 0,
        "latest_elapsed_ms": 35,
        "latency_delta_ms": 15,
        "latest_accept_rate": 0.6,
        "accept_rate_delta": -0.2,
        "latest_escalation_rate": 0.3,
        "escalation_rate_delta": 0.2,
        "active_failed_groups": ["quality_gateway"],
        "regressed_groups": ["quality_gateway"],
        "improved_groups": [],
        "trend": "regressing",
        "next_action": "inspect_regressed_groups",
    }


def test_chat_quality_trend_detects_improvement() -> None:
    old = _payload(
        passed=17,
        failed=1,
        groups={"trace_replay": 1},
    )
    current = _payload(
        passed=18,
        failed=0,
        groups={"trace_replay": 0},
    )

    trend = summarize_chat_quality_trend(current, [old])

    assert trend["trend"] == "improving"
    assert trend["failed_delta"] == -1
    assert trend["improved_groups"] == ["trace_replay"]
    assert trend["next_action"] == "continue_sampling"


def test_chat_quality_history_is_compact_jsonl(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    payload = _payload(
        passed=18,
        failed=0,
        groups={"golden_strategy": 0},
    )
    snapshot = chat_quality_trend_snapshot(payload, recorded_at="2026-07-10T12:00:00Z")

    append_chat_quality_trend_snapshot(path, snapshot)
    path.write_text(path.read_text() + "{bad json\n", encoding="utf-8")

    loaded = load_chat_quality_trend_history(path)

    assert loaded == [snapshot]
    assert "results" not in snapshot
    assert json.dumps(snapshot).find("prompt") == -1


def _payload(
    *,
    passed: int,
    failed: int,
    groups: dict[str, int],
    elapsed_ms: int | None = None,
    accept_rate: float | None = None,
    escalation_rate: float | None = None,
) -> dict[str, object]:
    return {
        "suite": "alpha_chat_quality",
        "suite_version": 1,
        "status": "failed" if failed else "passed",
        "passed": passed,
        "failed": failed,
        "case_groups": {
            group: {
                "case_count": 1,
                "passed": 0 if group_failed else 1,
                "failed": group_failed,
            }
            for group, group_failed in groups.items()
        },
        "scoreboard": {
            "accept_rate": accept_rate,
            "escalation_rate": escalation_rate,
        },
        "reporting": {"elapsed_ms": elapsed_ms},
    }
