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
    assert payload["case_groups"]["auto_context"]["case_count"] >= 7


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
    assert payload["passed"] >= 9
