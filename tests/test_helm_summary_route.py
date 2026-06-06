from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
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


class FakeApprovalConn:
    def __init__(self) -> None:
        self.fetchrow_calls: list[tuple[str, tuple[object, ...]]] = []
        self.fetchval_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetchrow(self, query: str, *args: object):
        self.fetchrow_calls.append((query, args))
        return None

    async def fetchval(self, query: str, *args: object):
        self.fetchval_calls.append((query, args))
        return "queue-1"


class FakeHelmActionConn:
    def __init__(self) -> None:
        self.fetch_calls: list[tuple[str, tuple[object, ...]]] = []

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        self.fetch_calls.append((query, args))
        action_filter = args[0] if args else []
        connector = (
            "medical"
            if isinstance(action_filter, list) and "connector:medical" in action_filter
            else "financial"
        )
        action_id = f"{connector}-pending-approvals"
        title = (
            "Review medical alert" if connector == "medical" else "Review paper gate"
        )
        requested_at = datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
        return [
            {
                "id": f"queue-{connector}",
                "action_class": [
                    "helm_action_proposal",
                    f"connector:{connector}",
                    f"action:{action_id}",
                ],
                "risk_tier": "T5",
                "status": "pending",
                "description": f"Helm proposal: {connector.title()} - {title}",
                "requested_at": requested_at,
                "expires_at": requested_at + timedelta(minutes=10),
            }
        ]


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


@pytest.mark.asyncio
async def test_helm_family_summary_requires_helm_read_scope() -> None:
    with pytest.raises(HTTPException) as exc:
        await helm.helm_family_summary(_request(), _user_id="ken")

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_helm_family_summary_brokers_family_service_token(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"children": [], "custody": {"is_ken_day": True}}

    class FakeClient:
        def __init__(self, *, timeout: float, verify: bool) -> None:
            calls["timeout"] = timeout
            calls["verify"] = verify

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url: str, *, headers: dict[str, str]):
            calls["url"] = url
            calls["headers"] = headers
            return FakeResponse()

    monkeypatch.setenv("JARVIS_FAMILY_API_URL", "https://family.invalid")
    monkeypatch.setattr(helm, "_family_service_token", lambda: "service-token")
    monkeypatch.setattr(helm.httpx, "AsyncClient", FakeClient)

    response = await helm.helm_family_summary(
        _request(scopes=["helm.read"]),
        _user_id="ken",
    )

    assert calls["url"] == "https://family.invalid/v1/helm/home-summary"
    assert calls["headers"] == {"Authorization": "Bearer service-token"}
    assert response["_broker"]["authority"] == "jarvis-alpha"
    assert response["_broker"]["source"] == "jarvis-family"


@pytest.mark.asyncio
async def test_helm_financial_summary_returns_alpha_queue_status(monkeypatch) -> None:
    conn = FakeHelmActionConn()

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source: str, audit_actor: str):
        assert source == "http"
        assert audit_actor == "helm_financial_summary:ken"
        yield conn

    monkeypatch.delenv("JARVIS_FINANCIAL_API_URL", raising=False)
    monkeypatch.setattr(
        helm, "platform_admin_connection", fake_platform_admin_connection
    )

    response = await helm.helm_financial_summary(
        _request(scopes=["helm.read"]),
        _user_id="ken",
    )

    assert conn.fetch_calls[0][1][0] == [
        "helm_action_proposal",
        "connector:financial",
    ]
    assert response["pending_approvals"] == 1
    assert response["paper"] == {"status": "read_only", "readiness": "brokered"}
    assert response["net_worth"] == {"status": "brokered"}
    assert response["approvals"]["items"][0]["connector_id"] == "financial"
    assert (
        response["approvals"]["items"][0]["action_id"] == "financial-pending-approvals"
    )
    assert "actor_sub" not in str(response)


@pytest.mark.asyncio
async def test_helm_medical_summary_brokers_redacted_family_export(monkeypatch) -> None:
    conn = FakeHelmActionConn()
    calls: dict[str, object] = {}

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source: str, audit_actor: str):
        assert source == "http"
        assert audit_actor == "helm_medical_summary:ken"
        yield conn

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "safety_status": "ok",
                "critical_facts": 2,
                "alerts": 0,
                "children": 2,
            }

    class FakeClient:
        def __init__(self, *, timeout: float, verify: bool) -> None:
            calls["timeout"] = timeout
            calls["verify"] = verify

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url: str, *, headers: dict[str, str]):
            calls["url"] = url
            calls["headers"] = headers
            return FakeResponse()

    monkeypatch.setenv("JARVIS_FAMILY_API_URL", "https://family.invalid")
    monkeypatch.setattr(helm, "_family_service_token", lambda: "service-token")
    monkeypatch.setattr(
        helm, "platform_admin_connection", fake_platform_admin_connection
    )
    monkeypatch.setattr(helm.httpx, "AsyncClient", FakeClient)

    response = await helm.helm_medical_summary(
        _request(scopes=["helm.read"]),
        _user_id="ken",
    )

    assert calls["url"] == "https://family.invalid/v1/helm/medical-summary"
    assert calls["headers"] == {"Authorization": "Bearer service-token"}
    assert response["safety_status"] == "ok"
    assert response["critical_facts"] == 2
    assert response["pending_approvals"] == 1
    assert response["approvals"]["items"][0]["connector_id"] == "medical"
    assert response["_broker"]["authority"] == "jarvis-alpha"
    assert response["_broker"]["source"] == "jarvis-family"
    assert "Sloane" not in str(response)


@pytest.mark.asyncio
async def test_helm_action_status_returns_redacted_status(monkeypatch) -> None:
    conn = FakeHelmActionConn()

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source: str, audit_actor: str):
        assert source == "http"
        assert audit_actor == "helm_action_status:ken"
        yield conn

    monkeypatch.setattr(
        helm, "platform_admin_connection", fake_platform_admin_connection
    )

    response = await helm.helm_action_status(
        _request(scopes=["helm.read"]),
        _user_id="ken",
    )
    payload = response.model_dump()

    assert conn.fetch_calls[0][1][0] == ["helm_action_proposal"]
    assert payload["actions"][0]["approval_queue_id"] == "queue-financial"
    assert payload["actions"][0]["title"] == "Review paper gate"
    assert payload["by_connector"] == {"financial": {"pending": 1}}
    assert "actor_sub" not in str(payload)


@pytest.mark.asyncio
async def test_helm_action_proposal_queues_approval(monkeypatch) -> None:
    conn = FakeApprovalConn()

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source: str, audit_actor: str):
        assert source == "http"
        assert audit_actor == "helm_action:ken"
        yield conn

    monkeypatch.setattr(
        helm, "platform_admin_connection", fake_platform_admin_connection
    )

    response = await helm.helm_action_proposal(
        _request(scopes=["helm.read"]),
        helm.HelmActionProposalRequest(
            connector_id="family",
            action_id="family-critical-alerts",
            title="Critical Family alert needs review",
            domain="Family",
            risk_tier="T4",
            idempotency_key="family-alert-key",
            payload={"private": "redacted before persistence"},
        ),
        _user_id="ken",
    )

    assert response.approval_queue_id == "queue-1"
    assert response.status == "pending"
    assert conn.fetchval_calls[0][1][0] == [
        "helm_action_proposal",
        "connector:family",
        "action:family-critical-alerts",
    ]
    assert conn.fetchval_calls[0][1][1] == "T4"
    assert (
        conn.fetchval_calls[0][1][4]
        == "Helm proposal: Family - Critical Family alert needs review"
    )
    assert conn.fetchval_calls[0][1][6] == "family-alert-key"
    assert "redacted before persistence" not in str(conn.fetchval_calls)


def test_helm_family_and_action_routes_are_classified() -> None:
    assert classify_route("GET", "/v1/helm/family/summary") == [
        "read",
        "security_read",
    ]
    assert classify_route("GET", "/v1/helm/financial/summary") == [
        "read",
        "security_read",
    ]
    assert classify_route("GET", "/v1/helm/medical/summary") == [
        "read",
        "security_read",
    ]
    assert classify_route("GET", "/v1/helm/actions/status") == [
        "read",
        "security_read",
    ]
    assert classify_route("POST", "/v1/helm/actions/propose") == [
        "write",
        "security_write",
    ]
