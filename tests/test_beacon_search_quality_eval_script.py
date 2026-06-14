from __future__ import annotations

import json
import os
import subprocess
import sys

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://127.0.0.1:8188")


def test_beacon_search_quality_eval_script_outputs_json() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/eval_beacon_search_quality.py"],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["status"] == "passed"
    assert payload["failed"] == 0
    assert payload["passed"] >= 3
