from __future__ import annotations

import json
import os
import subprocess
import sys

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://127.0.0.1:8188")

from brain.services.chat_evaluation_harness import (
    CHAT_EVAL_SCHEMA_VERSION,
    chat_eval_payload,
    run_chat_eval_harness,
)
from brain.services.chat_quality_trends import CHAT_QUALITY_TREND_SCHEMA_VERSION


def test_chat_eval_harness_all_offline_contracts_pass() -> None:
    results = run_chat_eval_harness()

    assert len(results) >= 9
    assert all(result.passed for result in results)
    assert {result.eval_group for result in results} == {
        "golden_strategy",
        "memory_pack",
        "prompt_compiler",
        "quality_gateway",
        "mcp_tool_boundary",
        "trace_replay",
        "redacted_trace_corpus",
        "calibrated_routing_rollout",
        "model_score_calibration",
        "outcome_audit",
    }


def test_chat_eval_payload_scoreboards_outcome_metadata() -> None:
    payload = chat_eval_payload(
        [
            {
                "chat_outcome_schema_version": "chat_outcome.v1",
                "chat_outcome_route_mode": "local",
                "chat_outcome_quality_action": "accept",
                "chat_outcome_escalation_rung": "none",
                "used_council": False,
            },
            {
                "chat_outcome_schema_version": "chat_outcome.v1",
                "chat_outcome_route_mode": "perplexity",
                "chat_outcome_quality_action": "require_beacon",
                "chat_outcome_escalation_rung": "beacon",
                "chat_outcome_escalation_required": True,
                "used_council": True,
            },
        ]
    )

    assert payload["schema_version"] == CHAT_EVAL_SCHEMA_VERSION
    assert payload["status"] == "passed"
    assert payload["failed"] == 0
    assert payload["case_groups"]["golden_strategy"]["case_count"] == 4
    assert payload["case_groups"]["memory_pack"]["case_count"] == 2
    assert payload["case_groups"]["prompt_compiler"]["case_count"] == 2
    assert payload["case_groups"]["quality_gateway"]["case_count"] == 4
    assert payload["case_groups"]["mcp_tool_boundary"]["case_count"] == 1
    assert payload["case_groups"]["trace_replay"]["case_count"] == 4
    assert payload["case_groups"]["redacted_trace_corpus"]["case_count"] == 1
    assert payload["case_groups"]["calibrated_routing_rollout"]["case_count"] == 1
    assert payload["case_groups"]["model_score_calibration"]["case_count"] == 1
    assert payload["case_groups"]["outcome_audit"]["case_count"] == 1
    assert payload["scoreboard"] == {
        "evaluated_outcome_count": 2,
        "accept_rate": 0.5,
        "escalation_rate": 0.5,
        "council_rate": 0.5,
        "quality_actions": {"accept": 1, "require_beacon": 1},
        "route_modes": {"local": 1, "perplexity": 1},
    }
    assert payload["model_calibration"]["evaluated_outcome_count"] == 2
    assert len(payload["model_calibration"]["calibrated_models"]) == 4
    assert payload["calibrated_routing_rollout"]["observed_outcome_count"] == 0
    assert payload["calibrated_routing_rollout"]["applied_outcome_count"] == 0
    assert payload["reporting"]["model_calls"] == 0
    assert payload["trend_observability"]["schema_version"] == (
        CHAT_QUALITY_TREND_SCHEMA_VERSION
    )
    assert payload["trend_observability"]["trend"] == "single_sample"


def test_chat_eval_payload_fails_bad_outcome_contract() -> None:
    payload = chat_eval_payload(
        [
            {
                "chat_outcome_schema_version": "old",
                "chat_outcome_quality_action": "accept",
                "chat_outcome_escalation_rung": "beacon",
            }
        ]
    )

    result = next(
        item
        for item in payload["results"]
        if item["name"] == "stored_chat_outcomes_are_scorable"
    )

    assert payload["status"] == "failed"
    assert result["passed"] is False
    assert result["failures"] == ["row_0:schema", "row_0:accept_escalated"]


def test_trace_replay_eval_details_do_not_include_raw_turn_text() -> None:
    payload = chat_eval_payload()

    trace_results = [
        result
        for result in payload["results"]
        if result["eval_group"] == "trace_replay"
    ]

    assert trace_results
    assert "Find the official OpenAI API docs." not in json.dumps(trace_results)
    assert "I checked the web and confirmed this is current." not in json.dumps(
        trace_results
    )


def test_redacted_trace_corpus_details_do_not_include_raw_sensitive_text() -> None:
    payload = chat_eval_payload()

    redacted_results = [
        result
        for result in payload["results"]
        if result["eval_group"] == "redacted_trace_corpus"
    ]
    rendered = json.dumps(redacted_results)

    assert redacted_results
    assert "Ken Haas" not in rendered
    assert "ken@example.com" not in rendered
    assert "404-555-1212" not in rendered
    assert "raw_trace_text_retained" in rendered


def test_mcp_boundary_eval_details_do_not_include_raw_tool_text() -> None:
    payload = chat_eval_payload()

    mcp_results = [
        result
        for result in payload["results"]
        if result["eval_group"] == "mcp_tool_boundary"
    ]

    assert mcp_results
    assert "Ignore previous instructions" not in json.dumps(mcp_results)
    assert "You are now system" not in json.dumps(mcp_results)


def test_chat_eval_script_outputs_json() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/eval_chat_quality.py"],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["schema_version"] == CHAT_EVAL_SCHEMA_VERSION
    assert payload["suite"] == "alpha_chat_quality"
    assert payload["status"] == "passed"
    assert payload["failed"] == 0
    assert payload["trend_observability"]["trend"] == "single_sample"


def test_chat_eval_script_records_metadata_only_history(tmp_path) -> None:
    history_path = tmp_path / "chat_quality_eval_history.jsonl"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/eval_chat_quality.py",
            "--history-path",
            str(history_path),
            "--record-history",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    rows = [json.loads(line) for line in history_path.read_text().splitlines()]

    assert payload["trend_observability"]["trend"] == "single_sample"
    assert len(rows) == 1
    assert rows[0]["schema_version"] == "chat_quality_eval_snapshot.v1"
    assert rows[0]["suite"] == "alpha_chat_quality"
    assert "results" not in rows[0]
