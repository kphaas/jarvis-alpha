from decimal import Decimal
from types import SimpleNamespace

import pytest

from brain.skills.policy_gate import SkillInvocation, SkillPolicyDecision
from brain.skills.runner import SkillCall
from brain.skills.secrets import rotate_secret, secrets_skill_handlers


def _call(payload):
    return SkillCall(
        invocation=SkillInvocation(
            agent_id="keyturner",
            skill_name="secrets.rotate",
            idempotency_key="rotate-test",
            approval_granted=True,
        ),
        decision=SkillPolicyDecision(
            outcome="allow",
            reason="policy_ok",
            agent_id="keyturner",
            skill_name="secrets.rotate",
            approval_tier="T4",
            skill_scope="secrets.rotate",
            estimated_cost_usd=Decimal("0"),
        ),
        payload=payload,
    )


@pytest.mark.asyncio
async def test_secrets_rotate_delegates_without_returning_secret(monkeypatch):
    seen = {}

    async def fake_rotate_key(req):
        seen["key_name"] = req.key_name
        seen["new_value"] = req.new_value
        return SimpleNamespace(
            status="rotated",
            rotation_id="rotation-123",
            key_name=req.key_name,
            old_key_health="passed",
            new_key_health="passed",
        )

    monkeypatch.setattr("brain.skills.secrets.rotate_key", fake_rotate_key)

    result = await rotate_secret(
        _call({"key_name": "ANTHROPIC_API_KEY", "new_value": "sk-ant-secret"})
    )

    assert seen == {"key_name": "ANTHROPIC_API_KEY", "new_value": "sk-ant-secret"}
    assert result == {
        "status": "rotated",
        "rotation_id": "rotation-123",
        "key_name": "ANTHROPIC_API_KEY",
        "old_key_health": "passed",
        "new_key_health": "passed",
        "approval_granted": True,
    }
    assert "sk-ant-secret" not in repr(result)


def test_secrets_skill_handlers_registers_rotate_handler():
    assert secrets_skill_handlers()["secrets.rotate"] is rotate_secret
