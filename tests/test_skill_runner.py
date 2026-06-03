from decimal import Decimal

import pytest

from brain.skills.policy_gate import SkillInvocation, SkillPolicyDecision
from brain.skills.runner import SkillCall, SkillRunner


def _decision(outcome="allow", reason="policy_ok"):
    return SkillPolicyDecision(
        outcome=outcome,
        reason=reason,
        agent_id="sweep",
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


class ApprovalAwareGate:
    def __init__(self):
        self.calls = []

    async def evaluate(self, conn, invocation):
        self.calls.append((conn, invocation))
        if invocation.approval_granted:
            return _decision(outcome="allow", reason="policy_ok")
        return _decision(outcome="approval_required", reason="t4_approval_required")


class FakeApprovalItem:
    def __init__(self, queue_id, status):
        self.queue_id = queue_id
        self.status = status


class FakeApprovalBridge:
    def __init__(self, approved=None):
        self.approved = approved
        self.queued = []
        self.consumed = []

    async def find_approved(self, conn, invocation, decision, payload):
        return self.approved

    async def queue_required(self, conn, invocation, decision, payload):
        item = FakeApprovalItem("queue-pending", "pending")
        self.queued.append((conn, invocation, decision, payload))
        return item

    async def consume(self, conn, queue_id):
        self.consumed.append((conn, queue_id))


@pytest.mark.asyncio
async def test_runner_executes_registered_handler_after_allow():
    seen: list[SkillCall] = []

    async def handler(call: SkillCall):
        seen.append(call)
        return {"ok": True, "device_count": call.payload["device_count"]}

    invocation = SkillInvocation(
        agent_id="sweep",
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
        SkillInvocation(agent_id="sweep", skill_name="unifi.wan_status"),
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
        SkillInvocation(agent_id="sweep", skill_name="unifi.wan_status"),
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
        SkillInvocation(agent_id="sweep", skill_name="unifi.wan_status"),
    )

    assert result.requires_approval
    assert result.decision.reason == "t4_approval_required"
    assert called is False


@pytest.mark.asyncio
async def test_runner_queues_approval_required_skill_when_bridge_configured():
    called = False
    bridge = FakeApprovalBridge()

    async def handler(call: SkillCall):
        nonlocal called
        called = True

    result = await SkillRunner(
        gate=FakeGate(
            _decision(outcome="approval_required", reason="t4_approval_required")
        ),
        handlers={"unifi.wan_status": handler},
        approval_bridge=bridge,
    ).run(
        object(),
        SkillInvocation(agent_id="sweep", skill_name="unifi.wan_status"),
        payload={"action": "pause_child_device"},
    )

    assert result.requires_approval
    assert result.approval_queue_id == "queue-pending"
    assert result.approval_status == "pending"
    assert len(bridge.queued) == 1
    assert called is False


@pytest.mark.asyncio
async def test_runner_consumes_approval_and_executes_retry():
    seen: list[SkillCall] = []
    gate = ApprovalAwareGate()
    bridge = FakeApprovalBridge(approved=FakeApprovalItem("queue-approved", "approved"))

    async def handler(call: SkillCall):
        seen.append(call)
        return {"approved": call.invocation.approval_granted}

    result = await SkillRunner(
        gate=gate,
        handlers={"unifi.wan_status": handler},
        approval_bridge=bridge,
    ).run(
        object(),
        SkillInvocation(agent_id="sweep", skill_name="unifi.wan_status"),
    )

    assert result.executed
    assert result.output == {"approved": True}
    assert result.approval_queue_id == "queue-approved"
    assert result.approval_status == "approved_consumed"
    assert seen[0].invocation.approval_granted is True
    assert bridge.consumed == [(gate.calls[0][0], "queue-approved")]
    assert [call[1].approval_granted for call in gate.calls] == [False, True]


@pytest.mark.asyncio
async def test_runner_does_not_queue_approval_for_missing_adapter():
    bridge = FakeApprovalBridge()

    result = await SkillRunner(
        gate=FakeGate(
            _decision(outcome="approval_required", reason="t4_approval_required")
        ),
        approval_bridge=bridge,
    ).run(
        object(),
        SkillInvocation(agent_id="sweep", skill_name="unifi.wan_status"),
    )

    assert result.denied
    assert result.decision.reason == "adapter_not_registered"
    assert bridge.queued == []


@pytest.mark.asyncio
async def test_runner_denies_allowed_skill_without_registered_adapter():
    result = await SkillRunner(gate=FakeGate(_decision())).run(
        object(),
        SkillInvocation(agent_id="sweep", skill_name="unifi.wan_status"),
    )

    assert result.denied
    assert result.decision.reason == "adapter_not_registered"


@pytest.mark.asyncio
async def test_runner_register_adds_handler():
    runner = SkillRunner(gate=FakeGate(_decision()))
    runner.register("unifi.wan_status", lambda call: {"registered": True})

    result = await runner.run(
        object(),
        SkillInvocation(agent_id="sweep", skill_name="unifi.wan_status"),
    )

    assert result.executed
    assert result.output == {"registered": True}
