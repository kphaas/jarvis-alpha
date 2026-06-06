from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from brain.middleware.approval_classes import classify_route
from brain.routes import helm


def _request(*, scopes: list[str] | None = None, role: str = "user"):
    return SimpleNamespace(
        state=SimpleNamespace(
            user_id="ken",
            role=role,
            actor_type="user",
            scopes=scopes or [],
        )
    )


class FakeConn:
    def __init__(self) -> None:
        self.fetch_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        self.fetch_calls.append((query, args))
        if "public.alpha_approval_queue" in query:
            return [
                {"risk_tier": "T4", "count": 2},
                {"risk_tier": "T5", "count": 1},
            ]
        if "public.alpha_skill_registry" in query:
            return [
                {"status": "active", "count": 8, "mutating": 3, "body_access": 1},
                {"status": "planned", "count": 2, "mutating": 1, "body_access": 0},
            ]
        if "WHERE agent_id = ANY" in query:
            return [
                {"status": "active", "enabled": True},
                {"status": "active", "enabled": True},
                {"status": "planned", "enabled": False},
            ]
        if "public.alpha_agents" in query:
            return [
                {"status": "active", "risk_tier": "T2", "enabled": True, "count": 4},
                {"status": "active", "risk_tier": "T4", "enabled": True, "count": 2},
                {"status": "planned", "risk_tier": "T4", "enabled": False, "count": 1},
            ]
        raise AssertionError(f"unexpected query: {query}")

    async def fetchrow(self, query: str, *args: object) -> dict[str, object]:
        self.fetchrow_calls.append((query, args))
        if "public.alpha_node_registry" in query:
            return {"is_active": True}
        raise AssertionError(f"unexpected query: {query}")


@pytest.mark.asyncio
async def test_helm_summary_requires_helm_read_scope() -> None:
    with pytest.raises(HTTPException) as exc:
        await helm.helm_summary(_request(), _user_id="ken")

    assert exc.value.status_code == 403
    assert exc.value.detail["required_scopes"] == ["helm.read", "admin"]


@pytest.mark.asyncio
async def test_helm_summary_returns_redacted_counts(monkeypatch) -> None:
    conn = FakeConn()
    captured: dict[str, object] = {}

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source: str, audit_actor: str):
        captured["source"] = source
        captured["audit_actor"] = audit_actor
        yield conn

    monkeypatch.setattr(
        helm, "platform_admin_connection", fake_platform_admin_connection
    )

    response = await helm.helm_summary(_request(scopes=["helm.read"]), _user_id="ken")
    payload = response.model_dump()

    assert captured == {"source": "http", "audit_actor": "helm_summary:ken"}
    assert payload["approvals"] == {
        "pending_total": 3,
        "by_tier": {"T4": 2, "T5": 1},
        "highest_tier": "T5",
    }
    assert payload["registry"]["skills"]["total"] == 10
    assert payload["registry"]["agents"]["enabled"] == 6
    assert payload["posture"]["gateway"] == {"state": "registered", "active": True}
    assert payload["posture"]["security_agents"] == {
        "total": 3,
        "enabled": 2,
        "by_status": {"active": 2, "planned": 1},
    }
    assert "description" not in str(payload)
    assert "actor_sub" not in str(payload)


def test_helm_summary_route_is_read_classified() -> None:
    assert classify_route("GET", "/v1/helm/summary") == ["read", "security_read"]
