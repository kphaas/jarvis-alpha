from __future__ import annotations

import json
import os

import pytest

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://127.0.0.1:8188")

from brain.routes import chat
from brain.services.chat_evidence_pack import (
    build_chat_evidence_pack,
    verify_chat_response,
)
from brain.services.chat_repair_loop import (
    ChatRepairAttemptResult,
    repair_chat_response_once,
    run_chat_repair_loop,
)


def test_repair_loop_strips_unsupported_web_narration() -> None:
    evidence_pack = build_chat_evidence_pack(
        memory_context="[current] Alpha plan: build the repair loop next.",
        internet_context=None,
    )
    verification = verify_chat_response(
        response_text=(
            "I checked the web and confirmed this. "
            "The current Alpha plan is to build the repair loop next."
        ),
        evidence_pack=evidence_pack,
    )

    repair = repair_chat_response_once(
        response_text=(
            "I checked the web and confirmed this. "
            "The current Alpha plan is to build the repair loop next."
        ),
        evidence_pack=evidence_pack,
        verification=verification,
    )

    assert repair.repaired is True
    assert repair.action == "strip_unsupported_web_claim"
    assert repair.text == "The current Alpha plan is to build the repair loop next."
    assert repair.verification.verified is True
    assert repair.to_metadata()["chat_repair_before_issues"] == [
        "unsupported_web_verification_claim"
    ]


def test_repair_loop_does_not_bypass_web_suggestion_confirmation() -> None:
    evidence_pack = build_chat_evidence_pack(
        memory_context="",
        internet_context=None,
        web_suggestion_context="Beacon has not run yet.",
    )
    verification = verify_chat_response(
        response_text="This needs current verification.",
        evidence_pack=evidence_pack,
    )

    repair = repair_chat_response_once(
        response_text="This needs current verification.",
        evidence_pack=evidence_pack,
        verification=verification,
    )

    assert repair.attempted is False
    assert repair.repaired is False
    assert repair.reason == "requires_beacon"
    assert repair.verification.requires_web_verification is True


@pytest.mark.asyncio
async def test_repair_loop_does_not_retry_empty_response_without_evidence() -> None:
    called = False
    evidence_pack = build_chat_evidence_pack(memory_context="", internet_context=None)

    async def retry_once(_prompt: str) -> ChatRepairAttemptResult:
        nonlocal called
        called = True
        return ChatRepairAttemptResult(text="should not run", model_used="local")

    repair = await run_chat_repair_loop(
        response_text="",
        user_msg="What is the current Alpha plan?",
        evidence_pack=evidence_pack,
        retry_once=retry_once,
    )

    assert called is False
    assert repair.attempted is False
    assert repair.reason == "no_evidence_for_repair"


@pytest.mark.asyncio
async def test_stream_single_retries_empty_response_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_route(prompt: str, mode: str) -> dict[str, object]:
        calls.append(mode)
        if len(calls) == 1:
            return {"result": "", "mode": mode, "chat_route_mode": mode}
        return {
            "result": "The current Alpha plan is to build the repair loop next.",
            "mode": "local",
            "chat_route_mode": "local",
        }

    monkeypatch.setattr(chat, "route", fake_route)
    outcome: dict[str, object] = {}
    evidence_pack = build_chat_evidence_pack(
        memory_context="[current] Alpha plan: build the repair loop next.",
        internet_context=None,
    )

    chunks = [
        chunk
        async for chunk in chat._stream_single(
            "User: What is the current Alpha plan?",
            "auto",
            "thread-1",
            "auto",
            "What is the current Alpha plan?",
            evidence_pack=evidence_pack,
            chat_outcome_holder=outcome,
        )
    ]

    streamed_text = _streamed_text(chunks)
    assert calls == ["auto", "local"]
    assert streamed_text == "The current Alpha plan is to build the repair loop next."
    assert outcome["chat_repair_action"] == "retry_local_once"
    assert outcome["chat_repair_repaired"] is True
    assert outcome["chat_outcome_quality_action"] == "accept"


def _streamed_text(chunks: list[str]) -> str:
    parts: list[str] = []
    for chunk in chunks:
        if not chunk.startswith("data: ") or "[DONE]" in chunk:
            continue
        payload = json.loads(chunk[6:])
        if "delta" in payload and not payload.get("done"):
            parts.append(str(payload["delta"]))
    return "".join(parts)
