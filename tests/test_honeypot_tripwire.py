import pytest

from brain.routes import honeypot


class _FakePool:
    pass


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
