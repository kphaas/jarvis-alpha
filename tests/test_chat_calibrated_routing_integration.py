from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://localhost/test")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://127.0.0.1:8188")

from brain.routes import chat
from brain.routing import router as chat_router
from brain.routing.calibrated_rollout import (
    CHAT_CALIBRATED_ROUTING_ROLLOUT_VERSION,
    ChatCalibratedRoutingPolicy,
)


@pytest.mark.asyncio
async def test_router_applies_active_calibrated_route_and_emits_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_subprocess_run(command: list[str], **_kwargs: object) -> object:
        payload = json.loads(command[command.index("-d") + 1])
        assert payload["provider"] == "gemini"
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(
                {
                    "result": {
                        "candidates": [
                            {"content": {"parts": [{"text": "Bounded answer."}]}}
                        ]
                    }
                }
            ),
        )

    monkeypatch.setattr(chat_router.subprocess, "run", fake_subprocess_run)
    result = await chat_router.route(
        "Summarize the AT-0 architecture tradeoffs.",
        "auto",
        routing_outcomes=_route_changing_outcomes(),
        rollout_key="thread-active",
        rollout_policy=ChatCalibratedRoutingPolicy(mode="active", rollout_percent=100),
    )

    assert result["mode"] == "gemini"
    assert result["result"] == "Bounded answer."
    assert result["chat_route_mode"] == "gemini"
    assert result["chat_calibrated_routing_schema_version"] == (
        CHAT_CALIBRATED_ROUTING_ROLLOUT_VERSION
    )
    assert result["chat_calibrated_routing_applied"] is True
    assert result["chat_calibrated_routing_baseline_route"] == "claude"
    assert result["chat_calibrated_routing_candidate_route"] == "gemini"
    assert "thread-active" not in json.dumps(result)


@pytest.mark.asyncio
async def test_explicit_model_bypasses_calibrated_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_subprocess_run(command: list[str], **_kwargs: object) -> object:
        payload = json.loads(command[command.index("-d") + 1])
        assert payload["provider"] == "gemini"
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(
                {
                    "result": {
                        "candidates": [
                            {"content": {"parts": [{"text": "Explicit answer."}]}}
                        ]
                    }
                }
            ),
        )

    monkeypatch.setattr(chat_router.subprocess, "run", fake_subprocess_run)
    result = await chat_router.route(
        "Summarize the AT-0 architecture tradeoffs.",
        "gemini",
        routing_outcomes=_route_changing_outcomes(),
        rollout_key="thread-explicit",
        rollout_policy=ChatCalibratedRoutingPolicy(mode="active", rollout_percent=100),
    )

    assert result["mode"] == "gemini"
    assert result["chat_strategy_reason"] == "explicit_model_requested"
    assert "chat_calibrated_routing_applied" not in result


@pytest.mark.asyncio
async def test_chat_loads_compact_outcomes_only_when_rollout_observes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake_list_chat_outcomes(**_kwargs: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "outcomes": [
                {
                    "chat_outcome_route_mode": "local",
                    "chat_outcome_quality_action": "accept",
                }
            ]
        }

    monkeypatch.setattr(chat, "list_chat_outcomes", fake_list_chat_outcomes)
    monkeypatch.setenv("ALPHA_CHAT_CALIBRATED_ROUTING_MODE", "off")
    assert await chat._load_calibrated_routing_outcomes(SimpleNamespace()) == ()
    assert calls == 0

    monkeypatch.setenv("ALPHA_CHAT_CALIBRATED_ROUTING_MODE", "shadow")
    outcomes = await chat._load_calibrated_routing_outcomes(SimpleNamespace())
    assert calls == 1
    assert outcomes == (
        {
            "chat_outcome_route_mode": "local",
            "chat_outcome_quality_action": "accept",
        },
    )


@pytest.mark.asyncio
async def test_chat_outcome_query_failure_degrades_to_static_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_list_chat_outcomes(**_kwargs: object) -> dict[str, object]:
        raise TimeoutError("database timeout")

    monkeypatch.setattr(chat, "list_chat_outcomes", failing_list_chat_outcomes)
    monkeypatch.setenv("ALPHA_CHAT_CALIBRATED_ROUTING_MODE", "active")

    assert await chat._load_calibrated_routing_outcomes(SimpleNamespace()) == ()


def _route_changing_outcomes() -> list[dict[str, object]]:
    outcomes: list[dict[str, object]] = []
    for _ in range(10):
        outcomes.extend(
            (
                {
                    "chat_outcome_route_mode": "claude",
                    "chat_outcome_quality_action": "replace_with_safe_fallback",
                    "chat_outcome_escalation_rung": "operator_review",
                    "chat_outcome_escalation_required": True,
                    "chat_outcome_fallback_used": True,
                    "chat_outcome_issue_count": 2,
                },
                {
                    "chat_outcome_route_mode": "gemini",
                    "chat_outcome_quality_action": "accept",
                    "chat_outcome_escalation_rung": "none",
                    "chat_outcome_escalation_required": False,
                    "chat_outcome_fallback_used": False,
                    "chat_outcome_issue_count": 0,
                },
            )
        )
    return outcomes
