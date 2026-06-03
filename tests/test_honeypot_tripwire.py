from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from brain.routes import honeypot


class _FakePool:
    pass


class _FakeRow(dict):
    def __getitem__(self, key):
        return self.get(key)


@pytest.mark.asyncio
async def test_tripwire_event_notifies_security_alerts(monkeypatch):
    emitted = []

    async def fake_emit(event, *, pool):
        emitted.append((event, pool))

    monkeypatch.setattr(honeypot, "emit_agent_event", fake_emit)

    pool = _FakePool()
    await honeypot._emit_tripwire_event(
        trap_path="/.env",
        source_ip="203.0.113.10",
        method="GET",
        user_agent="scanner" * 100,
        should_notify=True,
        pool=pool,
    )

    event, event_pool = emitted[0]
    assert event_pool is pool
    assert event.agent_id == "tripwire"
    assert event.event_type == "honeypot.hit"
    assert event.severity == "warning"
    assert event.channel_key == "security_alerts"
    assert event.notify is True
    assert event.payload["trap_path"] == "/.env"
    assert event.payload["source_ip"] == "203.0.113.10"
    assert len(event.payload["user_agent"]) == 200


@pytest.mark.asyncio
async def test_tripwire_event_can_record_without_notification(monkeypatch):
    emitted = []

    async def fake_emit(event, *, pool):
        emitted.append(event)

    monkeypatch.setattr(honeypot, "emit_agent_event", fake_emit)

    await honeypot._emit_tripwire_event(
        trap_path="/admin",
        source_ip="203.0.113.10",
        method="POST",
        user_agent="scanner",
        should_notify=False,
        pool=_FakePool(),
    )

    assert emitted[0].notify is False
    assert emitted[0].payload["notify_debounce_window"] == "15 minutes"


@pytest.mark.asyncio
async def test_honeypot_events_returns_tripwire_dashboard_shape(monkeypatch):
    seen = {}
    rows = [
        _FakeRow(
            id=7,
            trap_path="/.env",
            source_ip="203.0.113.10",
            method="GET",
            user_agent="scanner",
            captured_at=datetime(2026, 6, 3, 16, 45, tzinfo=UTC),
        )
    ]

    class FakeConn:
        async def fetch(self, query, *args):
            seen["fetch_query"] = query
            seen["fetch_args"] = args
            return rows

        async def fetchval(self, query, *args):
            if "COUNT(DISTINCT source_ip)" in query:
                return 1
            if "INTERVAL '24 hours'" in query:
                return 2
            return 9

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source, audit_actor, pool=None):
        seen["source"] = source
        seen["audit_actor"] = audit_actor
        yield FakeConn()

    monkeypatch.setattr(
        honeypot, "platform_admin_connection", fake_platform_admin_connection
    )
    monkeypatch.setattr(honeypot, "get_pool", lambda: _FakePool())
    request = SimpleNamespace(
        state=SimpleNamespace(actor_type="user", role="admin", scopes=[])
    )

    response = await honeypot.get_honeypot_events(request, limit=50)

    assert seen["source"] == "http"
    assert seen["audit_actor"] == "tripwire_events"
    assert seen["fetch_args"] == (50,)
    assert response["agent_id"] == "tripwire"
    assert response["display_name"] == "Tripwire"
    assert response["total"] == 9
    assert response["hits_24h"] == 2
    assert response["unique_clients_24h"] == 1
    assert response["traps_active"] == len(honeypot.TRIPWIRE_TRAPS)
    assert response["events"] == [
        {
            "id": 7,
            "ts": "2026-06-03T16:45:00+00:00",
            "path": "/.env",
            "trap_type": "env_file",
            "client_ip": "203.0.113.10",
            "user_agent": "scanner",
            "method": "GET",
        }
    ]


@pytest.mark.asyncio
async def test_persist_event_uses_platform_admin_rls_context(monkeypatch):
    seen = {}
    emitted = {}

    class FakeConn:
        async def execute(self, query, *args):
            seen["execute_query"] = query
            seen["execute_args"] = args

        async def fetchval(self, query, *args):
            seen["fetchval_query"] = query
            seen["fetchval_args"] = args
            return False

    @asynccontextmanager
    async def fake_platform_admin_connection(*, source, audit_actor, pool=None):
        seen["source"] = source
        seen["audit_actor"] = audit_actor
        yield FakeConn()

    async def fake_emit_tripwire_event(**kwargs):
        emitted.update(kwargs)

    monkeypatch.setattr(
        honeypot, "platform_admin_connection", fake_platform_admin_connection
    )
    monkeypatch.setattr(honeypot, "get_pool", lambda: _FakePool())
    monkeypatch.setattr(honeypot, "_emit_tripwire_event", fake_emit_tripwire_event)

    request = SimpleNamespace(
        client=SimpleNamespace(host="203.0.113.10"),
        headers={"user-agent": "scanner", "x-test": "1"},
        method="GET",
    )

    await honeypot._persist_event(request, "/.env")

    assert seen["source"] == "http"
    assert seen["audit_actor"] == "tripwire_honeypot"
    assert "INSERT INTO public.alpha_honeypot_events" in seen["execute_query"]
    assert seen["execute_args"][:4] == ("/.env", "203.0.113.10", "GET", "scanner")
    assert seen["fetchval_args"] == (
        honeypot.TRIPWIRE_AGENT_ID,
        honeypot.TRIPWIRE_EVENT_TYPE,
        "/.env",
        "203.0.113.10",
    )
    assert emitted["trap_path"] == "/.env"
    assert emitted["source_ip"] == "203.0.113.10"
    assert emitted["should_notify"] is True
