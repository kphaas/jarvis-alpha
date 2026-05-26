"""No-op governance canary skills."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from brain.skills.runner import SkillCall


class ApprovalCanaryPayload(BaseModel):
    label: str = Field(default="approval-bridge-canary", max_length=80)
    expected_operator: str = Field(default="ken", max_length=80)


async def approval_canary_t4(call: SkillCall) -> dict[str, Any]:
    """Return a harmless proof that a T4 skill passed the approval bridge."""

    payload = ApprovalCanaryPayload.model_validate(dict(call.payload))
    return {
        "status": "canary_ok",
        "skill_name": call.invocation.skill_name,
        "agent_id": call.invocation.agent_id,
        "idempotency_key": call.invocation.idempotency_key,
        "approval_granted": call.invocation.approval_granted,
        "label": payload.label,
        "expected_operator": payload.expected_operator,
    }


def canary_skill_handlers() -> dict[str, Any]:
    return {
        "approval.canary_t4": approval_canary_t4,
    }
