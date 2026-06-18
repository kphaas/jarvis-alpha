from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


SCRIPT_PATH = Path("scripts/smoke_mvp_external_data.py")
SPEC = importlib.util.spec_from_file_location("smoke_mvp_external_data", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
smoke_mvp_external_data = importlib.util.module_from_spec(SPEC)
sys.modules["smoke_mvp_external_data"] = smoke_mvp_external_data
SPEC.loader.exec_module(smoke_mvp_external_data)


def test_mvp_smoke_local_checks_pass():
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        check=True,
    )

    payload = json.loads(result.stdout)

    assert payload["status"] == "passed"
    assert payload["checks"]["registry_coverage"]["status"] == "passed"
    assert payload["checks"]["weather_current"]["status"] == "passed"
    assert payload["checks"]["beacon_sources"]["status"] == "passed"
    assert (
        payload["checks"]["approval_egress_guardrails"]["detail"][
            "browser_task_decision"
        ]
        == "approval_required"
    )


def test_live_detail_requires_gateway_token_when_requested():
    detail = {
        "service_health": {
            "brain": {"status": "passed"},
            "gateway": {"status": "passed"},
            "endpoint": {"status": "passed"},
            "sandbox": {"status": "passed"},
        },
        "gateway_token_gated": {
            "status": "skipped",
            "reason": "gateway token not available",
        },
    }

    assert smoke_mvp_external_data._live_detail_passed(
        detail, require_gateway_token=False
    )
    assert not smoke_mvp_external_data._live_detail_passed(
        detail, require_gateway_token=True
    )
