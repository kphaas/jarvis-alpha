"""Unit tests for brain/routes/internal.py — POST /v1/internal/complete.

Covers scope enforcement, model whitelist, happy path, Ollama-unreachable
handling, the side-effect-free guarantee (no memory/embedding), and the
metadata-only structured log line (no prompt/response text).

Handlers are invoked directly with a SimpleNamespace request (the repo's
route-unit-test convention), with the Ollama primitive mocked — zero network.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_GATEWAY_URL", "https://localhost:8283")

import brain.routes.internal as internal
from brain.core.models import LOCAL_CHAT, LOCAL_CODE


def _request(*, scopes: list[str] | None = None, iss: str = "print"):
    return SimpleNamespace(
        state=SimpleNamespace(
            user_id=f"{iss}_service",
            role="service",
            actor_type="service",
            scopes=scopes or [],
            iss=iss,
        )
    )


def _fake_generate(response: dict[str, Any]):
    async def _gen(**_kwargs: Any) -> dict[str, Any]:
        return response

    return _gen


# ── Scope enforcement ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rejects_caller_without_llm_complete_scope() -> None:
    body = internal.CompleteRequest(model=LOCAL_CHAT, prompt="hello")
    with pytest.raises(HTTPException) as exc:
        await internal.complete(body, _request(scopes=["health.read"]))
    assert exc.value.status_code == 403
    assert exc.value.detail["required_scopes"] == ["llm:complete"]


# ── Model whitelist ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rejects_model_outside_whitelist() -> None:
    body = internal.CompleteRequest(model="gpt-4o", prompt="hello")
    with pytest.raises(HTTPException) as exc:
        await internal.complete(body, _request(scopes=["llm:complete"]))
    assert exc.value.status_code == 400
    assert exc.value.detail["error"] == "model not allowed"
    assert set(exc.value.detail["allowed"]) == {LOCAL_CHAT, LOCAL_CODE}


# ── Happy path ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_returns_result_and_token_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        internal,
        "generate",
        _fake_generate(
            {"response": "tuned!", "prompt_eval_count": 11, "eval_count": 7}
        ),
    )
    body = internal.CompleteRequest(model=LOCAL_CODE, prompt="tune this")
    resp = await internal.complete(body, _request(scopes=["llm:complete"]))

    assert resp.model == LOCAL_CODE
    assert resp.result == "tuned!"
    assert resp.tokens.prompt == 11
    assert resp.tokens.completion == 7
    assert resp.latency_ms >= 0


# ── Ollama unreachable → 503 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_ollama_unreachable_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _boom(**_kwargs: Any) -> dict[str, Any]:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(internal, "generate", _boom)
    body = internal.CompleteRequest(model=LOCAL_CHAT, prompt="hello")
    with pytest.raises(HTTPException) as exc:
        await internal.complete(body, _request(scopes=["llm:complete"]))
    assert exc.value.status_code == 503
    assert exc.value.detail["error"] == "llm backend unavailable"
    # No backend stack/detail leaked.
    assert "connection refused" not in str(exc.value.detail)


# ── No memory / embedding side effects ─────────────────────────────


@pytest.mark.asyncio
async def test_no_memory_or_embedding_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import brain.memory.memory as memory_mod
    import brain.routes.ask as ask_mod

    mem_cls = MagicMock(name="MemoryService")
    embed_mock = MagicMock(name="_embed")
    monkeypatch.setattr(memory_mod, "MemoryService", mem_cls)
    monkeypatch.setattr(ask_mod, "_embed", embed_mock)
    monkeypatch.setattr(
        internal, "generate", _fake_generate({"response": "ok", "eval_count": 1})
    )

    body = internal.CompleteRequest(model=LOCAL_CHAT, prompt="secret prompt")
    await internal.complete(body, _request(scopes=["llm:complete"]))

    assert mem_cls.call_count == 0
    assert embed_mock.call_count == 0


# ── Structured log: metadata only, never prompt/response text ──────


@pytest.mark.asyncio
async def test_log_line_is_metadata_only(monkeypatch: pytest.MonkeyPatch) -> None:
    log_mock = MagicMock()
    monkeypatch.setattr(internal, "logger", log_mock)
    monkeypatch.setattr(
        internal,
        "generate",
        _fake_generate(
            {"response": "SENSITIVE_OUTPUT", "prompt_eval_count": 3, "eval_count": 5}
        ),
    )

    body = internal.CompleteRequest(model=LOCAL_CHAT, prompt="SENSITIVE_PROMPT")
    await internal.complete(body, _request(scopes=["llm:complete"], iss="print"))

    log_mock.info.assert_called_once()
    extra = log_mock.info.call_args.kwargs["extra"]
    assert extra["issuer"] == "print"
    assert extra["model"] == LOCAL_CHAT
    assert extra["status"] == "ok"
    assert extra["prompt_tokens"] == 3
    assert extra["completion_tokens"] == 5
    assert "latency_ms" in extra

    # Privacy: neither prompt nor response text appears anywhere in the log call.
    serialized = repr(log_mock.info.call_args)
    assert "SENSITIVE_PROMPT" not in serialized
    assert "SENSITIVE_OUTPUT" not in serialized
