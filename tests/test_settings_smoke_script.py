from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


SCRIPT_PATH = Path("scripts/smoke_settings.py")
SPEC = importlib.util.spec_from_file_location("smoke_settings", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
smoke_settings = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = smoke_settings
SPEC.loader.exec_module(smoke_settings)


def test_smoke_token_uses_explicit_settings_token(monkeypatch):
    monkeypatch.setenv("SETTINGS_SMOKE_TOKEN", "settings-token")
    monkeypatch.setenv("ALPHA_TEST_TOKEN", "stale-test-token")
    monkeypatch.setenv("ALPHA_SERVICE_TOKEN", "stale-service-token")

    token = smoke_settings._smoke_token(
        profile="ken",
        base_url=smoke_settings.DEFAULT_BASE_URL,
        token_ssh_target=None,
    )

    assert token == "settings-token"


def test_smoke_token_uses_target_side_generation(monkeypatch):
    monkeypatch.delenv("SETTINGS_SMOKE_TOKEN", raising=False)
    monkeypatch.setenv("ALPHA_TEST_TOKEN", "stale-test-token")
    monkeypatch.setenv("ALPHA_SERVICE_TOKEN", "stale-service-token")
    calls: list[list[str]] = []

    def fake_check_output(cmd, *, text, stderr):
        calls.append(cmd)
        return "target-token\n"

    monkeypatch.setattr(
        smoke_settings.subprocess,
        "check_output",
        fake_check_output,
    )

    token = smoke_settings._smoke_token(
        profile="ken",
        base_url=smoke_settings.DEFAULT_BASE_URL,
        token_ssh_target="jarvisbrain@example.test",
    )

    assert token == "target-token"
    assert calls[0][0] == "ssh"
    assert calls[0][-2] == "jarvisbrain@example.test"
    assert "scripts/gen_test_token.py ken" in calls[0][-1]


def test_remote_smoke_without_token_source_fails_explicitly(monkeypatch):
    monkeypatch.delenv("SETTINGS_SMOKE_TOKEN", raising=False)
    monkeypatch.setenv("ALPHA_TEST_TOKEN", "stale-test-token")
    monkeypatch.setenv("ALPHA_SERVICE_TOKEN", "stale-service-token")

    with pytest.raises(RuntimeError, match="SETTINGS_SMOKE_TOKEN"):
        smoke_settings._smoke_token(
            profile="ken",
            base_url=smoke_settings.DEFAULT_BASE_URL,
            token_ssh_target=None,
        )


def test_identity_settings_check_passes_without_printing_personal_data():
    result = smoke_settings._check_identity_settings(
        {
            "profiles": [
                {
                    "id": "ken",
                    "display_name": "Ken",
                    "personal_data": {
                        "email": "ken@example.test",
                        "phone": "555-555-5555",
                    },
                }
            ],
            "relationships": [{"from_profile_id": "ken", "to_profile_id": "sloane"}],
            "personal_data": {
                "home_address": {"street1": "123 Private Ln"},
                "storage_classification": "alpha_db_personal_settings",
            },
        }
    )

    assert result.ok is True
    assert result.metadata == {
        "profile_count": 1,
        "relationship_count": 1,
        "profiles_with_personal_data_count": 1,
        "storage_classification": "alpha_db_personal_settings",
        "home_address_present": True,
    }


def test_identity_settings_check_fails_when_contract_is_missing():
    result = smoke_settings._check_identity_settings(
        {
            "profiles": [],
            "relationships": {},
            "personal_data": {"storage_classification": "unknown"},
        }
    )

    assert result.ok is False
    assert result.status == "failed"


def test_web_agent_settings_requires_configured_home_location_by_default():
    result = smoke_settings._check_web_agent_settings(
        {"home_location": None, "storage_classification": "alpha_db_personal_settings"},
        require_home_location=True,
    )

    assert result.ok is False
    assert result.metadata["home_location_present"] is False


def test_web_agent_settings_check_passes_with_coordinates_without_printing_them():
    result = smoke_settings._check_web_agent_settings(
        {
            "home_location": {
                "label": "Home",
                "city": "Johns Creek",
                "region": "GA",
                "postal_code": "30022",
                "latitude": 34.0,
                "longitude": -84.0,
            },
            "storage_classification": "alpha_db_personal_settings",
        },
        require_home_location=True,
    )

    assert result.ok is True
    assert result.metadata == {
        "storage_classification": "alpha_db_personal_settings",
        "home_location_present": True,
        "home_location_coordinates_present": True,
        "home_location_city_present": True,
        "home_location_region_present": True,
        "home_location_postal_code_present": True,
    }


def test_endpoint_settings_route_check_requires_react_root():
    assert (
        smoke_settings._check_endpoint_settings_route(
            '<html><body><div id="root"></div></body></html>'
        ).ok
        is True
    )
    assert smoke_settings._check_endpoint_settings_route("<html></html>").ok is False
