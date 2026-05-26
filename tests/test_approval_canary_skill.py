from decimal import Decimal

import pytest

from brain.skills.canary import approval_canary_t4, canary_skill_handlers
from brain.skills.policy_gate import SkillInvocation, SkillPolicyDecision
from brain.skills.runner import SkillCall, SkillRunner


def _decision(outcome="allow", reason="policy_ok"):
    return SkillPolicyDecision(
        outcome=outcome,
        reason=reason,
        agent_id="approval_canary",
        skill_name="approval.canary_t4",
        approval_tier="T4",
        skill_scope="approval.canary",
        estimated_cost_usd=Decimal("0"),
    )


class FakeGate:
    async def evaluate(self, conn, invocation):
        if invocation.approval_granted:
            return _decision()
        return _decision("approval_required", "t4_approval_required")


class FakeApprovalItem:
    queue_id = "canary-queue"
    status = "approved"


class FakeApprovalBridge:
    def __init__(self):
        self.consumed = []

    async def find_approved(self, conn, invocation, decision, payload):
        return FakeApprovalItem()

    async def queue_required(self, conn, invocation, decision, payload):
        raise AssertionError("approved item should have been used")

    async def consume(self, conn, queue_id):
        self.consumed.append(queue_id)


@pytest.mark.asyncio
async def test_approval_canary_handler_is_harmless_and_structured():
    call = SkillCall(
        invocation=SkillInvocation(
            agent_id="approval_canary",
            skill_name="approval.canary_t4",
            idempotency_key="canary-1",
            approval_granted=True,
        ),
        decision=_decision(),
        payload={"label": "approval bridge test"},
    )

    result = await approval_canary_t4(call)

    assert result == {
        "status": "canary_ok",
        "skill_name": "approval.canary_t4",
        "agent_id": "approval_canary",
        "idempotency_key": "canary-1",
        "approval_granted": True,
        "label": "approval bridge test",
        "expected_operator": "ken",
    }


@pytest.mark.asyncio
async def test_approval_canary_executes_only_after_bridge_approval():
    bridge = FakeApprovalBridge()
    runner = SkillRunner(
        gate=FakeGate(),
        handlers=canary_skill_handlers(),
        approval_bridge=bridge,
    )

    result = await runner.run(
        object(),
        SkillInvocation(
            agent_id="approval_canary",
            skill_name="approval.canary_t4",
            idempotency_key="canary-2",
        ),
        payload={"label": "approved retry"},
    )

    assert result.executed
    assert result.approval_queue_id == "canary-queue"
    assert result.approval_status == "approved_consumed"
    assert result.output["approval_granted"] is True
    assert result.output["label"] == "approved retry"
    assert bridge.consumed == ["canary-queue"]
