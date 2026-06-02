from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import brain.db.pool as db_pool
import brain.db.rls as db_rls
from brain.routes import security
from brain.routes.pin_auth import _profile_scopes


def test_child_profile_scopes_exclude_vault_and_admin_surface():
    assert _profile_scopes("child") == ["ask", "chat.read", "health.read"]
    assert "vault.read" not in _profile_scopes("child")
    assert _profile_scopes("admin") == ["*"]


class FakeConn:
    async def fetch(self, query, *args):
        if "FROM public.alpha_profiles" in query:
            return [
                {
                    "id": "ryleigh",
                    "display_name": "Ryleigh",
                    "role": "child",
                    "child_age": 8,
                    "max_rating": "age_8_plus",
                },
                {
                    "id": "sloane",
                    "display_name": "Sloane",
                    "role": "child",
                    "child_age": 5,
                    "max_rating": "all_ages",
                },
            ]
        if "FROM pg_class" in query:
            return [
                {
                    "relname": table,
                    "rls_enabled": True,
                    "force_enabled": True,
                    "policy_count": 1,
                }
                for table in security._CHILD_SENSITIVE_TABLES
            ]
        if "FROM pg_policies" in query:
            return []
        raise AssertionError(query)


@asynccontextmanager
async def fake_platform_admin_connection(*args, **kwargs):
    yield FakeConn()


@pytest.mark.asyncio
async def test_child_profile_security_status_is_live_and_avatar_limited(monkeypatch):
    request = SimpleNamespace(state=SimpleNamespace(role="admin", actor_type="user"))
    monkeypatch.setattr(db_pool, "get_pool", lambda: object())
    monkeypatch.setattr(
        db_rls, "platform_admin_connection", fake_platform_admin_connection
    )

    result = await security.child_profiles(request)

    assert result["overall"] == "full"
    assert result["legacy_child_policies"] == []
    assert [profile["id"] for profile in result["profiles"]] == ["ryleigh", "sloane"]
    for profile in result["profiles"]:
        assert profile["scopes"] == ["ask", "chat.read", "health.read"]
        assert profile["allowed_surfaces"] == ["voice", "avatar"]
        assert profile["surface_filter"] is True
