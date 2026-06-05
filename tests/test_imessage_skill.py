from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from brain.skills.imessage import imessage_skill_handlers
from brain.skills.policy_gate import SkillInvocation, SkillPolicyDecision
from brain.skills.runner import SkillCall


@dataclass(frozen=True)
class _Counts:
    total_chats: int = 1218
    imessage_chats: int = 484
    sms_chats: int = 706
    rcs_chats: int = 28
    sent_messages: int = 3496


@dataclass(frozen=True)
class _Recent:
    status: int = 200
    message: str = "Success"
    count: int = 5
    total: int = 1218
    offset: int = 0
    limit: int = 5
    data_count: int = 5


class _Client:
    async def counts(self):
        return _Counts()

    async def recent_chat_metadata(self, *, limit: int, offset: int):
        assert limit == 5
        assert offset == 0
        return _Recent()


def _call(payload=None):
    return SkillCall(
        invocation=SkillInvocation(agent_id="ken_voice", skill_name="imessage.read"),
        decision=SkillPolicyDecision(
            outcome="allow",
            reason="policy_ok",
            agent_id="ken_voice",
            skill_name="imessage.read",
            approval_tier="T1",
            skill_scope="imessage.read",
            body_scope="imessage.body.read",
            cost_spent_today_usd=Decimal("0"),
            estimated_cost_usd=Decimal("0"),
        ),
        payload=payload or {},
    )


@pytest.mark.asyncio
async def test_imessage_read_skill_returns_counts_without_body_access() -> None:
    handler = imessage_skill_handlers(client=_Client())["imessage.read"]

    result = await handler(_call())

    assert result["total_chats"] == 1218
    assert result["sent_messages"] == 3496
    assert result["body_access"] is False


@pytest.mark.asyncio
async def test_imessage_read_skill_returns_recent_metadata_only() -> None:
    handler = imessage_skill_handlers(client=_Client())["imessage.read"]

    result = await handler(_call({"action": "recent_chat_metadata"}))

    assert result["total"] == 1218
    assert result["data_count"] == 5
    assert result["body_access"] is False
