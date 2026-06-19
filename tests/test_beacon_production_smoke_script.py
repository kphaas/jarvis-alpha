from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path("scripts/smoke_beacon_production.py")
SPEC = importlib.util.spec_from_file_location("smoke_beacon_production", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
smoke_beacon_production = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke_beacon_production)


def test_smoke_token_uses_explicit_beacon_token(monkeypatch):
    monkeypatch.setenv("BEACON_SMOKE_TOKEN", "beacon-token")
    monkeypatch.setenv("ALPHA_TEST_TOKEN", "stale-test-token")
    monkeypatch.setenv("ALPHA_SERVICE_TOKEN", "stale-service-token")

    token = smoke_beacon_production._smoke_token(
        profile="ken",
        base_url=smoke_beacon_production.DEFAULT_BASE_URL,
        token_ssh_target=None,
    )

    assert token == "beacon-token"


def test_smoke_token_uses_target_side_generation(monkeypatch):
    monkeypatch.delenv("BEACON_SMOKE_TOKEN", raising=False)
    monkeypatch.setenv("ALPHA_TEST_TOKEN", "stale-test-token")
    monkeypatch.setenv("ALPHA_SERVICE_TOKEN", "stale-service-token")
    calls: list[list[str]] = []

    def fake_check_output(cmd, *, text, stderr):
        calls.append(cmd)
        return "target-token\n"

    monkeypatch.setattr(
        smoke_beacon_production.subprocess,
        "check_output",
        fake_check_output,
    )

    token = smoke_beacon_production._smoke_token(
        profile="ken",
        base_url=smoke_beacon_production.DEFAULT_BASE_URL,
        token_ssh_target="jarvisbrain@example.test",
    )

    assert token == "target-token"
    assert calls[0][0] == "ssh"
    assert calls[0][-2] == "jarvisbrain@example.test"
    assert "scripts/gen_test_token.py ken" in calls[0][-1]


def test_remote_smoke_without_token_source_fails_explicitly(monkeypatch):
    monkeypatch.delenv("BEACON_SMOKE_TOKEN", raising=False)
    monkeypatch.setenv("ALPHA_TEST_TOKEN", "stale-test-token")
    monkeypatch.setenv("ALPHA_SERVICE_TOKEN", "stale-service-token")

    with pytest.raises(RuntimeError, match="BEACON_SMOKE_TOKEN"):
        smoke_beacon_production._smoke_token(
            profile="ken",
            base_url=smoke_beacon_production.DEFAULT_BASE_URL,
            token_ssh_target=None,
        )


def test_health_check_metadata_extracts_browser_runtime_limits():
    metadata = smoke_beacon_production._health_check_metadata(
        {
            "browser_runtime": {
                "status": "ok",
                "metadata": {
                    "runtime": "playwright",
                    "timeout_ms": 20_000,
                    "max_steps": 5,
                    "max_runs_per_hour": 3,
                },
            }
        },
        "browser_runtime",
    )

    assert metadata["max_steps"] == 5
    assert smoke_beacon_production._int(metadata["timeout_ms"]) == 20_000


def test_health_check_metadata_missing_check_is_empty():
    assert smoke_beacon_production._health_check_metadata({}, "browser_runtime") == {}
    assert smoke_beacon_production._int("not-a-number") == 0


def test_gateway_health_summary_surfaces_provider_route():
    summary = smoke_beacon_production._gateway_health_summary(
        {
            "gateway": {
                "status": "ok",
                "metadata": {
                    "primary_provider": "searxng",
                    "provider_order": ["searxng", "brave"],
                    "usable_provider_count": 2,
                    "required_provider_count": 2,
                    "provider_redundancy_status": "redundant",
                    "provider_warning_status": None,
                },
            }
        }
    )

    assert summary == {
        "status": "ok",
        "primary_provider": "searxng",
        "provider_order": ["searxng", "brave"],
        "usable_provider_count": 2,
        "required_provider_count": 2,
        "provider_redundancy_status": "redundant",
        "provider_warning_status": None,
    }
