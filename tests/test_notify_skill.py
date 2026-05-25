from decimal import Decimal

import pytest

from brain.skills.notify import (
    PushoverSkillError,
    notify_skill_handlers,
    send_pushover,
)
from brain.skills.policy_gate import SkillInvocation, SkillPolicyDecision
from brain.skills.runner import SkillCall


def _call(payload=None, *, idempotency_key="notify-test-1"):
    invocation = SkillInvocation(
        agent_id="buddy",
        skill_name="notify.send_pushover",
        idempotency_key=idempotency_key,
    )
    decision = SkillPolicyDecision(
        outcome="allow",
        reason="policy_ok",
        agent_id="buddy",
        skill_name="notify.send_pushover",
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

    def fake_post(payload, *, idempotency_key, timeout_sec=15):
        seen["payload"] = payload
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

    def fake_post(payload, *, idempotency_key, timeout_sec=15):
        seen.update(payload)
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
