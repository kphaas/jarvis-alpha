from decimal import Decimal

import pytest

from brain.skills.notify import (
    MattermostSkillError,
    PushoverSkillError,
    notify_skill_handlers,
    send_mattermost,
    send_notify,
    send_pushover,
)
from brain.skills.policy_gate import SkillInvocation, SkillPolicyDecision
from brain.skills.runner import SkillCall


def _call(
    payload=None,
    *,
    skill_name="notify.send_pushover",
    idempotency_key="notify-test-1",
):
    invocation = SkillInvocation(
        agent_id="buddy",
        skill_name=skill_name,
        idempotency_key=idempotency_key,
    )
    decision = SkillPolicyDecision(
        outcome="allow",
        reason="policy_ok",
        agent_id="buddy",
        skill_name=skill_name,
        approval_tier="T2",
        skill_scope="notify.send",
        estimated_cost_usd=Decimal("0"),
    )
    return SkillCall(
        invocation=invocation,
        decision=decision,
        payload=payload
        or {
            "title": "Alpha",
            "message": "hello",
            "priority": -1,
        },
    )


@pytest.mark.asyncio
async def test_send_pushover_calls_gateway_with_idempotency_key(monkeypatch):
    seen = {}

    def fake_post(payload, *, provider, idempotency_key, timeout_sec=15):
        seen["payload"] = payload
        seen["provider"] = provider
        seen["idempotency_key"] = idempotency_key
        seen["timeout_sec"] = timeout_sec
        return 0, '{"status":"sent","request_id":"abc","receipt":"r1"}'

    monkeypatch.setattr("brain.skills.notify._post_gateway_notify_sync", fake_post)

    result = await send_pushover(_call())

    assert result == {
        "status": "sent",
        "provider": "pushover",
        "request_id": "abc",
        "receipt": "r1",
    }
    assert seen["idempotency_key"] == "notify-test-1"
    assert seen["provider"] == "pushover"
    assert seen["payload"]["title"] == "Alpha"


@pytest.mark.asyncio
async def test_send_pushover_requires_idempotency_key(monkeypatch):
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("brain.skills.notify._post_gateway_notify_sync", fake_post)

    with pytest.raises(PushoverSkillError, match="idempotency_key_required"):
        await send_pushover(_call(idempotency_key=None))

    assert called is False


@pytest.mark.asyncio
async def test_send_pushover_fills_emergency_retry_and_expire(monkeypatch):
    seen = {}

    def fake_post(payload, *, provider, idempotency_key, timeout_sec=15):
        seen.update(payload)
        seen["provider"] = provider
        return 0, '{"status":"sent","request_id":"urgent"}'

    monkeypatch.setattr("brain.skills.notify._post_gateway_notify_sync", fake_post)

    await send_pushover(
        _call(
            {
                "title": "Critical",
                "message": "wake up",
                "priority": 2,
            }
        )
    )

    assert seen["retry"] == 60
    assert seen["expire"] == 3600


@pytest.mark.asyncio
async def test_send_pushover_rejects_gateway_error(monkeypatch):
    monkeypatch.setattr(
        "brain.skills.notify._post_gateway_notify_sync",
        lambda *args, **kwargs: (0, '{"detail":"Pushover rejected notification"}'),
    )

    with pytest.raises(PushoverSkillError, match="Pushover rejected notification"):
        await send_pushover(_call())


def test_notify_skill_handlers_exports_pushover_handler():
    assert notify_skill_handlers()["notify.send_pushover"] is send_pushover


@pytest.mark.asyncio
async def test_send_mattermost_calls_gateway_with_channel_key(monkeypatch):
    seen = {}

    def fake_post(payload, *, provider, idempotency_key, timeout_sec=15):
        seen["payload"] = payload
        seen["provider"] = provider
        seen["idempotency_key"] = idempotency_key
        seen["timeout_sec"] = timeout_sec
        return 0, '{"status":"sent","post_id":"post-1","channel_id":"chan-1"}'

    monkeypatch.setattr("brain.skills.notify._post_gateway_notify_sync", fake_post)

    result = await send_mattermost(
        _call(
            {
                "title": "Alpha",
                "message": "hello",
                "severity": "warning",
                "channel_key": "agents",
            },
            skill_name="notify.send_mattermost",
        )
    )

    assert result == {
        "status": "sent",
        "provider": "mattermost",
        "post_id": "post-1",
        "channel_id": "chan-1",
    }
    assert seen["provider"] == "mattermost"
    assert seen["idempotency_key"] == "notify-test-1"
    assert seen["payload"]["channel_key"] == "agents"


@pytest.mark.asyncio
async def test_send_mattermost_requires_idempotency_key(monkeypatch):
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr("brain.skills.notify._post_gateway_notify_sync", fake_post)

    with pytest.raises(MattermostSkillError, match="idempotency_key_required"):
        await send_mattermost(
            _call(skill_name="notify.send_mattermost", idempotency_key=None)
        )

    assert called is False


@pytest.mark.asyncio
async def test_send_notify_uses_mattermost_primary(monkeypatch):
    seen = {}

    def fake_post(payload, *, provider, idempotency_key, timeout_sec=15):
        seen["provider"] = provider
        seen["payload"] = payload
        return 0, '{"status":"sent","post_id":"post-1","channel_id":"chan-1"}'

    monkeypatch.setattr("brain.skills.notify._post_gateway_notify_sync", fake_post)

    result = await send_notify(
        _call(
            {
                "title": "Alpha",
                "message": "normal ops",
                "severity": "info",
            },
            skill_name="notify.send",
        )
    )

    assert result == {
        "status": "sent",
        "provider": "mattermost",
        "post_id": "post-1",
        "channel_id": "chan-1",
        "fallback_used": False,
    }
    assert seen["provider"] == "mattermost"
    assert seen["payload"]["channel_key"] == "alerts"


@pytest.mark.asyncio
async def test_send_notify_falls_back_to_pushover(monkeypatch):
    calls = []

    def fake_post(payload, *, provider, idempotency_key, timeout_sec=15):
        calls.append((provider, payload, idempotency_key))
        if provider == "mattermost":
            return 0, '{"detail":"Mattermost transport failed"}'
        return 0, '{"status":"sent","request_id":"push-1","receipt":null}'

    monkeypatch.setattr("brain.skills.notify._post_gateway_notify_sync", fake_post)

    result = await send_notify(
        _call(
            {
                "title": "Critical",
                "message": "ops channel down",
                "severity": "critical",
            },
            skill_name="notify.send",
        )
    )

    assert result == {
        "status": "sent",
        "provider": "pushover",
        "request_id": "push-1",
        "receipt": None,
        "fallback_used": True,
        "primary_provider": "mattermost",
    }
    assert [call[0] for call in calls] == ["mattermost", "pushover"]
    assert calls[1][1]["priority"] == 1


def test_notify_skill_handlers_exports_primary_handlers():
    handlers = notify_skill_handlers()

    assert handlers["notify.send"] is send_notify
    assert handlers["notify.send_mattermost"] is send_mattermost
