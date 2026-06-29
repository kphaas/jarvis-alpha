from __future__ import annotations

import json
import os
import subprocess
import sys

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://127.0.0.1:8188")


def test_beacon_answer_engine_eval_script_outputs_json() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/eval_beacon_answer_engine.py"],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["suite"] == "beacon_answer_engine"
    assert payload["status"] == "passed"
    assert payload["failed"] == 0
    assert payload["passed"] >= 10
    assert payload["case_groups"]["focus_modes"]["failed"] == 0
    assert payload["case_groups"]["provider_telemetry"]["failed"] == 0
    assert payload["reporting"]["cost"]["mode"] == "offline_fixture"
    assert payload["reporting"]["citation_precision"]["precision"] > 0
