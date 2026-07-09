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


def test_chat_eval_harness_all_offline_contracts_pass() -> None:
    results = run_chat_eval_harness()

    assert len(results) >= 9
    assert all(result.passed for result in results)
    assert {result.eval_group for result in results} == {
        "golden_strategy",
        "prompt_compiler",
        "quality_gateway",
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
    assert payload["case_groups"]["prompt_compiler"]["case_count"] == 2
    assert payload["case_groups"]["quality_gateway"]["case_count"] == 4
    assert payload["case_groups"]["outcome_audit"]["case_count"] == 1
    assert payload["scoreboard"] == {
        "evaluated_outcome_count": 2,
        "accept_rate": 0.5,
        "escalation_rate": 0.5,
        "council_rate": 0.5,
        "quality_actions": {"accept": 1, "require_beacon": 1},
        "route_modes": {"local": 1, "perplexity": 1},
    }
    assert payload["reporting"]["model_calls"] == 0


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
