from __future__ import annotations

from pathlib import Path


PIN_AUTH_PATH = Path(__file__).resolve().parents[1] / "brain/routes/pin_auth.py"
PIN_AUTH_SOURCE = PIN_AUTH_PATH.read_text(encoding="utf-8")


def test_pin_auth_profile_access_uses_platform_admin_rls_context() -> None:
    assert "from brain.db.pool import get_pool" not in PIN_AUTH_SOURCE
    assert "platform_admin_connection" in PIN_AUTH_SOURCE
    assert "SELECT * FROM alpha_profiles" in PIN_AUTH_SOURCE

    for audit_actor in {
        "auth_pin",
        "auth_login_profiles",
        "auth_profiles_admin",
        "auth_set_child_pin",
        "auth_set_profile_pin",
        "auth_set_admin_pin",
    }:
        assert f'audit_actor="{audit_actor}"' in PIN_AUTH_SOURCE
