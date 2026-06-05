"""Read-only iMessage skills for Spark."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Literal

from pydantic import BaseModel, Field

from brain.services.bluebubbles_client import BlueBubblesReadOnlyClient
from brain.skills.runner import SkillCall


class IMessageReadPayload(BaseModel):
    action: Literal["health", "counts", "recent_chat_metadata"] = "counts"
    limit: int = Field(default=5, ge=1, le=25)
    offset: int = Field(default=0, ge=0)


async def read(call: SkillCall) -> dict[str, Any]:
    payload = IMessageReadPayload.model_validate(_public_payload(call))
    client = _client_from_call(call)

    if payload.action == "health":
        return {**asdict(await client.health()), "body_access": False}
    if payload.action == "recent_chat_metadata":
        metadata = await client.recent_chat_metadata(
            limit=payload.limit,
            offset=payload.offset,
        )
        return {**asdict(metadata), "body_access": False}
    return {**asdict(await client.counts()), "body_access": False}


def imessage_skill_handlers(
    client: BlueBubblesReadOnlyClient | None = None,
) -> dict[str, Any]:
    if client is None:
        return {"imessage.read": read}

    async def _read(call: SkillCall) -> dict[str, Any]:
        payload = IMessageReadPayload.model_validate(_public_payload(call))
        if payload.action == "health":
            return {**asdict(await client.health()), "body_access": False}
        if payload.action == "recent_chat_metadata":
            metadata = await client.recent_chat_metadata(
                limit=payload.limit,
                offset=payload.offset,
            )
            return {**asdict(metadata), "body_access": False}
        return {**asdict(await client.counts()), "body_access": False}

    return {"imessage.read": _read}


def _client_from_call(call: SkillCall) -> BlueBubblesReadOnlyClient:
    injected = call.payload.get("_client")
    if injected is not None:
        return injected
    return BlueBubblesReadOnlyClient()


def _public_payload(call: SkillCall) -> dict[str, Any]:
    return {
        key: value for key, value in call.payload.items() if not key.startswith("_")
    }
