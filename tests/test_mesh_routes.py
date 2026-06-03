from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest

from brain.routes import mesh


class _FakePool:
    pass


class _FakeRow(dict):
    def __getitem__(self, key):
        return self.get(key)


def _registry_row(**overrides):
    row = {
        "name": "brain",
        "display_name": "Brain",
        "role": "Orchestration",
        "node_type": "service",
        "tailscale_ip": "100.64.166.22",
        "health_endpoint": "https://jarvis-brain.tail40ed36.ts.net:8186/health",
        "cert_issued_at": datetime(2026, 3, 18, tzinfo=UTC),
        "cert_expires_at": datetime(2026, 9, 18, tzinfo=UTC),
        "is_active": True,
    }
    row.update(overrides)
    return _FakeRow(**row)


@pytest.mark.asyncio
async def test_mesh_status_uses_platform_admin_rls_context(monkeypatch):
    seen = {}

    class FakeConn:
        async def fetch(self, query, *args):
            seen["query"] = query
            seen["args"] = args
            return [_registry_row()]

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source, audit_actor, pool=None):
        seen["source"] = source
        seen["audit_actor"] = audit_actor
        yield FakeConn()

    monkeypatch.setattr(mesh, "get_pool", lambda: _FakePool())
    monkeypatch.setattr(
        mesh, "platform_admin_connection", fake_platform_admin_connection
    )
    monkeypatch.setattr(
        mesh,
        "_run_polymorphic_check",
        lambda row: ("healthy", {"response_time_ms": 12.3}),
    )

    response = await mesh.get_mesh_status()

    assert seen["source"] == "http"
    assert seen["audit_actor"] == "mesh_status"
    assert "public.alpha_node_registry" in seen["query"]
    assert response["mesh_status"] == "nominal"
    assert response["nodes"][0]["name"] == "brain"
    assert response["nodes"][0]["status"] == "healthy"
    assert response["nodes"][0]["cert_days_remaining"] is not None


@pytest.mark.asyncio
async def test_mesh_certs_uses_platform_admin_rls_context(monkeypatch):
    seen = {}

    class FakeConn:
        async def fetch(self, query, *args):
            seen["query"] = query
            seen["args"] = args
            return [_registry_row(name="gateway", display_name="Gateway")]

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source, audit_actor, pool=None):
        seen["source"] = source
        seen["audit_actor"] = audit_actor
        yield FakeConn()

    monkeypatch.setattr(mesh, "get_pool", lambda: _FakePool())
    monkeypatch.setattr(
        mesh, "platform_admin_connection", fake_platform_admin_connection
    )
    monkeypatch.setattr(mesh, "_presented_cert_expiry", lambda _url: None)

    response = await mesh.get_cert_status()

    assert seen["source"] == "http"
    assert seen["audit_actor"] == "mesh_certs"
    assert "public.alpha_node_registry" in seen["query"]
    assert response[0]["node"] == "Gateway"
    assert response[0]["domain"] == "jarvis-brain.tail40ed36.ts.net"
    assert response[0]["days_remaining"] is not None


@pytest.mark.asyncio
async def test_mesh_certs_prefers_presented_tls_cert(monkeypatch):
    class FakeConn:
        async def fetch(self, query, *args):
            return [
                _registry_row(
                    name="gateway",
                    display_name="Gateway",
                    cert_expires_at=datetime(2026, 6, 18, tzinfo=UTC),
                )
            ]

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source, audit_actor, pool=None):
        yield FakeConn()

    monkeypatch.setattr(mesh, "get_pool", lambda: _FakePool())
    monkeypatch.setattr(
        mesh, "platform_admin_connection", fake_platform_admin_connection
    )
    monkeypatch.setattr(
        mesh,
        "_presented_cert_expiry",
        lambda _url: datetime(2026, 7, 19, tzinfo=UTC),
    )

    response = await mesh.get_cert_status()

    assert response[0]["expires"] == "2026-07-19"
    assert response[0]["source"] == "tls"
