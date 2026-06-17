"""Unit tests for the local-LLM dispatch path (PR #428 shipped untested).

Covers the two task-executor handlers that reach the local model and the
shared Ollama primitive they call:

* ``brain.tasks.dispatch.call_code_agent`` — code generation handler.
* ``brain.tasks.dispatch.call_llm_agent``  — generic LLM handler.
* ``brain.services.ollama_client.generate`` — the single HTTP primitive.

The handlers patch the ``generate`` reference imported into ``dispatch`` (the
repo's route/handler-unit-test convention) and the primitive patches
``httpx.AsyncClient`` with a recording fake — zero network.
"""

from __future__ import annotations

import os
from typing import Any

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://localhost/db")
os.environ.setdefault("ALPHA_GATEWAY_URL", "https://localhost:8283")

import httpx
import pytest

import brain.services.ollama_client as ollama_client
import brain.tasks.dispatch as dispatch


def _recording_generate(response: dict[str, Any]):
    """Return a fake ``generate`` coroutine plus the list it records calls into."""
    calls: list[dict[str, Any]] = []

    async def _gen(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return response

    return _gen, calls


# ── call_code_agent ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_code_agent_uses_coder_model_and_system_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gen, calls = _recording_generate({"response": "def add(a, b):\n    return a + b"})
    monkeypatch.setattr(dispatch, "generate", gen)

    step = {"config": {"prompt": "write an add function", "language": "python"}}
    result = await dispatch.call_code_agent(step)

    # Coder model, not the chat model.
    assert len(calls) == 1
    assert calls[0]["model"] == "qwen2.5-coder:7b"

    # The prompt carries both the system framing and the user request.
    sent_prompt = calls[0]["prompt"]
    assert "code generation assistant" in sent_prompt
    assert "clean python code" in sent_prompt
    assert "write an add function" in sent_prompt

    # Output shape: the raw model response under ``code`` plus the language.
    assert result["success"] is True
    assert result["output"] == {
        "code": "def add(a, b):\n    return a + b",
        "language": "python",
    }


# ── call_llm_agent (the LLM dispatch fn) ───────────────────────────


@pytest.mark.asyncio
async def test_call_llm_agent_defaults_to_chat_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gen, calls = _recording_generate({"response": "hello there"})
    monkeypatch.setattr(dispatch, "generate", gen)

    step = {"config": {"prompt": "say hi"}}
    result = await dispatch.call_llm_agent(step)

    # Default model when config omits one.
    assert len(calls) == 1
    assert calls[0]["model"] == "llama3.1:8b"
    assert calls[0]["prompt"] == "say hi"

    # Output shape: the raw model response under ``response``.
    assert result["success"] is True
    assert result["output"] == {"response": "hello there"}


@pytest.mark.asyncio
async def test_call_llm_agent_honors_config_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gen, calls = _recording_generate({"response": "ok"})
    monkeypatch.setattr(dispatch, "generate", gen)

    step = {"config": {"prompt": "tune", "model": "qwen2.5-coder:7b"}}
    await dispatch.call_llm_agent(step)

    assert calls[0]["model"] == "qwen2.5-coder:7b"


# ── ollama_client.generate ─────────────────────────────────────────


class _FakeResponse:
    def __init__(self, json_data: dict[str, Any], exc: Exception | None = None):
        self._json = json_data
        self._exc = exc

    def raise_for_status(self) -> None:
        if self._exc is not None:
            raise self._exc

    def json(self) -> dict[str, Any]:
        return self._json


def _make_client(captured: dict[str, Any], response: _FakeResponse):
    """Build a fake ``httpx.AsyncClient`` that records construction + POST args."""

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any):
            captured["init_kwargs"] = kwargs

        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a: Any) -> bool:
            return False

        async def post(self, url: str, json: dict[str, Any] | None = None):
            captured["url"] = url
            captured["payload"] = json
            return response

    return _FakeClient


@pytest.mark.asyncio
async def test_generate_posts_non_stream_with_60s_timeout_returns_raw_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    raw = {"response": "tuned!", "prompt_eval_count": 11, "eval_count": 7}
    monkeypatch.setattr(
        ollama_client.httpx, "AsyncClient", _make_client(captured, _FakeResponse(raw))
    )

    result = await ollama_client.generate(model="llama3.1:8b", prompt="hi")

    # Non-streaming POST to /api/generate.
    assert captured["url"].endswith("/api/generate")
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["model"] == "llama3.1:8b"
    assert captured["payload"]["prompt"] == "hi"

    # 60-second client timeout.
    assert captured["init_kwargs"]["timeout"] == 60.0

    # Raw Ollama JSON returned verbatim (token counts preserved).
    assert result == raw


@pytest.mark.asyncio
async def test_generate_propagates_httpx_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    boom = httpx.ConnectError("connection refused")
    monkeypatch.setattr(
        ollama_client.httpx,
        "AsyncClient",
        _make_client(captured, _FakeResponse({}, exc=boom)),
    )

    # Transport / HTTP errors propagate — the primitive never swallows them.
    with pytest.raises(httpx.HTTPError):
        await ollama_client.generate(model="llama3.1:8b", prompt="hi")
