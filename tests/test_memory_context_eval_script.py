from __future__ import annotations

import json
import os
import subprocess
import sys

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://127.0.0.1:8188")

from brain.services.memory_context_evals import (
    memory_context_eval_payload,
    run_memory_context_evals,
)


def test_memory_context_evals_all_pass() -> None:
    results = run_memory_context_evals()

    assert len(results) >= 9
    assert all(result.passed for result in results)


def test_memory_context_eval_payload_groups_contracts() -> None:
    payload = memory_context_eval_payload()

    assert payload["suite"] == "memory_context"
    assert payload["status"] == "passed"
    assert payload["failed"] == 0
    assert payload["case_groups"]["user_visible_management"]["case_count"] == 2
    assert payload["case_groups"]["auto_context"]["case_count"] >= 8


def test_memory_context_eval_payload_scoreboard_contracts() -> None:
    payload = memory_context_eval_payload()

    scoreboard = payload["scoreboard"]
    assert set(scoreboard) == {
        "current_vs_old",
        "deleted_memories",
        "do_not_remember",
        "profile_recall",
        "at0_system_recall",
        "mixed_ken_at0",
    }
    assert all(row["status"] == "passed" for row in scoreboard.values())
    assert scoreboard["mixed_ken_at0"]["cases"] == [
        "mixed_ken_at0_prompt_selects_system_and_current_graph"
    ]


def test_memory_context_eval_script_outputs_json() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/eval_memory_context.py"],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["suite"] == "memory_context"
    assert payload["status"] == "passed"
    assert payload["failed"] == 0
    assert payload["passed"] >= 10
    assert payload["scoreboard"]["current_vs_old"]["status"] == "passed"
