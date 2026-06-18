from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit


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


def test_weather_current_path_includes_explicit_smoke_coordinates():
    path = smoke_mvp_external_data._weather_current_path(
        latitude=40.7128,
        longitude=-74.006,
    )
    parsed = urlsplit(path)
    params = parse_qs(parsed.query)

    assert parsed.path == "/v1/weather/current"
    assert params["latitude"] == ["40.712800"]
    assert params["longitude"] == ["-74.006000"]
    assert params["location_label"] == ["mvp-smoke"]


def test_gateway_token_reads_configured_secret_file(monkeypatch, tmp_path):
    secrets_file = tmp_path / ".secrets"
    secrets_file.write_text(
        "OTHER_TOKEN=ignored\nALPHA_SERVICE_TOKEN='service-token'\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GATEWAY_TOKEN", raising=False)
    monkeypatch.delenv("ALPHA_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("ALPHA_BRAIN_SERVICE_TOKEN", raising=False)
    monkeypatch.setenv("SECRETS_FILE", str(secrets_file))

    assert smoke_mvp_external_data._gateway_token() == "service-token"
