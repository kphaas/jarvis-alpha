from __future__ import annotations

from typing import Any

import pytest

from brain.routing import router
from brain.routing.generation_policy import (
    CHAT_GENERATION_POLICY_SCHEMA_VERSION,
    ChatGenerationPolicy,
)


def test_exact_key_policy_requires_json_mode_and_unique_keys() -> None:
    with pytest.raises(ValueError, match="require JSON mode"):
        ChatGenerationPolicy(exact_json_keys=("status",))
    with pytest.raises(ValueError, match="must be unique"):
        ChatGenerationPolicy(
            json_mode=True,
            exact_json_keys=("status", "status"),
        )


@pytest.mark.asyncio
async def test_local_router_applies_and_reports_generation_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    policy = ChatGenerationPolicy(
        deterministic=True,
        json_mode=True,
        exact_json_keys=("status",),
    )

    async def fake_generate(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"response": '{"status":"ready"}'}

    monkeypatch.setattr(router, "generate", fake_generate)

    result = await router.route(
        "Return JSON.",
        mode="local",
        generation_policy=policy,
    )

    assert captured == {
        "model": "llama3.1:8b",
        "prompt": "Return JSON.",
        "generation_policy": policy,
    }
    assert result["result"] == '{"status":"ready"}'
    assert result["chat_generation_policy_schema_version"] == (
        CHAT_GENERATION_POLICY_SCHEMA_VERSION
    )
    assert result["chat_deterministic_decoding_applied"] is True
    assert result["chat_structured_output_applied"] is True
    assert result["chat_exact_key_schema_applied"] is True
    assert result["chat_generation_policy_exact_key_count"] == 1
