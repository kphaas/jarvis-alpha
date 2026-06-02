"""Security secret management skills."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from brain.routes.rotation import RotateRequest, rotate_key
from brain.skills.runner import SkillCall


class SecretRotatePayload(BaseModel):
    key_name: str = Field(min_length=1, max_length=120)
    new_value: str = Field(min_length=1, max_length=4096)


async def rotate_secret(call: SkillCall) -> dict[str, Any]:
    """Rotate one approved secret through the existing Gateway proxy."""

    payload = SecretRotatePayload.model_validate(dict(call.payload))
    response = await rotate_key(
        RotateRequest(key_name=payload.key_name, new_value=payload.new_value)
    )
    return {
        "status": response.status,
        "rotation_id": response.rotation_id,
        "key_name": response.key_name,
        "old_key_health": response.old_key_health,
        "new_key_health": response.new_key_health,
        "approval_granted": call.invocation.approval_granted,
    }


def secrets_skill_handlers() -> dict[str, Any]:
    return {
        "secrets.rotate": rotate_secret,
    }
