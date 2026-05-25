from decimal import Decimal

import pytest

from brain.skills.policy_gate import SkillInvocation, SkillPolicyDecision
from brain.skills.runner import SkillCall, SkillRunner


def _decision(outcome="allow", reason="policy_ok"):
    return SkillPolicyDecision(
        outcome=outcome,
        reason=reason,
        agent_id="network_watchdog",
        skill_name="unifi.wan_status",
        approval_tier="T1",
        skill_scope="network.read",
        estimated_cost_usd=Decimal("0"),
    )


class FakeGate:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    async def evaluate(self, conn, invocation):
        self.calls.append((conn, invocation))
        return self.decision


@pytest.mark.asyncio
async def test_runner_executes_registered_handler_after_allow():
    seen: list[SkillCall] = []

    async def handler(call: SkillCall):
        seen.append(call)
        return {"ok": True, "device_count": call.payload["device_count"]}

    invocation = SkillInvocation(
        agent_id="network_watchdog",
        skill_name="unifi.wan_status",
    )
    runner = SkillRunner(
        gate=FakeGate(_decision()),
        handlers={"unifi.wan_status": handler},
    )

    result = await runner.run(object(), invocation, payload={"device_count": 3})

    assert result.executed
    assert result.output == {"ok": True, "device_count": 3}
    assert seen[0].invocation is invocation
    assert seen[0].decision.allowed


@pytest.mark.asyncio
async def test_runner_supports_sync_handlers():
    def handler(call: SkillCall):
        return {"skill": call.invocation.skill_name}

    result = await SkillRunner(
        gate=FakeGate(_decision()),
        handlers={"unifi.wan_status": handler},
    ).run(
        object(),
        SkillInvocation(agent_id="network_watchdog", skill_name="unifi.wan_status"),
    )

    assert result.executed
    assert result.output == {"skill": "unifi.wan_status"}


@pytest.mark.asyncio
async def test_runner_does_not_execute_when_policy_denies():
    called = False

    async def handler(call: SkillCall):
        nonlocal called
        called = True

    result = await SkillRunner(
        gate=FakeGate(_decision(outcome="deny", reason="agent_disabled")),
        handlers={"unifi.wan_status": handler},
    ).run(
        object(),
        SkillInvocation(agent_id="network_watchdog", skill_name="unifi.wan_status"),
    )

    assert result.denied
    assert result.decision.reason == "agent_disabled"
    assert called is False


@pytest.mark.asyncio
async def test_runner_does_not_execute_when_approval_required():
    called = False

    async def handler(call: SkillCall):
        nonlocal called
        called = True

    result = await SkillRunner(
        gate=FakeGate(
            _decision(outcome="approval_required", reason="t4_approval_required")
        ),
        handlers={"unifi.wan_status": handler},
    ).run(
        object(),
        SkillInvocation(agent_id="network_watchdog", skill_name="unifi.wan_status"),
    )

    assert result.requires_approval
    assert result.decision.reason == "t4_approval_required"
    assert called is False


@pytest.mark.asyncio
async def test_runner_denies_allowed_skill_without_registered_adapter():
    result = await SkillRunner(gate=FakeGate(_decision())).run(
        object(),
        SkillInvocation(agent_id="network_watchdog", skill_name="unifi.wan_status"),
    )

    assert result.denied
    assert result.decision.reason == "adapter_not_registered"


@pytest.mark.asyncio
async def test_runner_register_adds_handler():
    runner = SkillRunner(gate=FakeGate(_decision()))
    runner.register("unifi.wan_status", lambda call: {"registered": True})

    result = await runner.run(
        object(),
        SkillInvocation(agent_id="network_watchdog", skill_name="unifi.wan_status"),
    )

    assert result.executed
    assert result.output == {"registered": True}
