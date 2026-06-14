from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import pytest

from brain.memory import memory as memory_module
from brain.memory.memory import MemoryService


@dataclass(frozen=True)
class FakeSparkGrounding:
    def to_context_block(self) -> str:
        return "[WHO YOU'RE TALKING TO]\n- Principal: ken."


@pytest.mark.asyncio
async def test_build_context_injects_spark_grounding_before_semantic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(memory_module, "fetch_personality_memory", _async_rows([]))
    monkeypatch.setattr(
        memory_module,
        "load_spark_memory_grounding",
        lambda **_kwargs: FakeSparkGrounding(),
    )
    monkeypatch.setattr(
        MemoryService,
        "_get_semantic",
        _async_rows([{"fact": "Stable memory fact."}]),
    )
    monkeypatch.setattr(MemoryService, "_get_episodic", _async_rows([]))
    monkeypatch.setattr(MemoryService, "_get_working", _async_rows([]))

    context = await MemoryService().build_context(
        conn=object(),
        user_id=uuid4(),
        prompt="Draft this.",
        session_id="thread-1",
        embedding=[],
        principal_id="ken",
    )

    assert "[WHO YOU'RE TALKING TO]" in context
    assert "[ALWAYS KNOWN]" in context
    assert context.index("[WHO YOU'RE TALKING TO]") < context.index("[ALWAYS KNOWN]")


@pytest.mark.asyncio
async def test_build_context_prefers_approved_personality_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_loader(**_kwargs: object) -> None:
        raise AssertionError("vault fallback should not be used")

    monkeypatch.setattr(
        memory_module,
        "fetch_personality_memory",
        _async_rows([{"kind": "voice", "content": "Voice should feel composed."}]),
    )
    monkeypatch.setattr(memory_module, "load_spark_memory_grounding", raise_loader)
    monkeypatch.setattr(
        MemoryService,
        "_get_semantic",
        _async_rows([{"fact": "Stable memory fact."}]),
    )
    monkeypatch.setattr(MemoryService, "_get_episodic", _async_rows([]))
    monkeypatch.setattr(MemoryService, "_get_working", _async_rows([]))

    context = await MemoryService().build_context(
        conn=object(),
        user_id=uuid4(),
        prompt="Draft this.",
        session_id="thread-1",
        embedding=[],
        principal_id="ken",
    )

    assert "- Voice: Voice should feel composed." in context
    assert context.index("[WHO YOU'RE TALKING TO]") < context.index("[ALWAYS KNOWN]")


@pytest.mark.asyncio
async def test_build_context_degrades_when_spark_grounding_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_loader(**_kwargs: object) -> None:
        raise RuntimeError("vault missing")

    async def raise_fetch(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise RuntimeError("table unavailable")

    monkeypatch.setattr(memory_module, "fetch_personality_memory", raise_fetch)
    monkeypatch.setattr(memory_module, "load_spark_memory_grounding", raise_loader)
    monkeypatch.setattr(
        MemoryService,
        "_get_semantic",
        _async_rows([{"fact": "Stable memory fact."}]),
    )
    monkeypatch.setattr(MemoryService, "_get_episodic", _async_rows([]))
    monkeypatch.setattr(MemoryService, "_get_working", _async_rows([]))

    context = await MemoryService().build_context(
        conn=object(),
        user_id=uuid4(),
        prompt="Draft this.",
        session_id="thread-1",
        embedding=[],
        principal_id="ken",
    )

    assert "[WHO YOU'RE TALKING TO]" not in context
    assert "[ALWAYS KNOWN]\n- Stable memory fact." in context


@pytest.mark.asyncio
async def test_semantic_memory_uses_prompt_relevance_when_prompt_present() -> None:
    conn = _CapturingConn()
    user_id = uuid4()

    rows = await MemoryService()._get_semantic(
        conn,
        user_id,
        prompt="What should Spark remember about Sweta?",
    )

    assert rows == [{"fact": "Ranked fact", "category": "preference", "source": "test"}]
    assert "websearch_to_tsquery" in conn.sql
    assert "ts_rank_cd" in conn.sql
    assert conn.args == (user_id, 50, "What should Spark remember about Sweta?")


def _async_rows(rows: list[dict[str, object]]):
    async def inner(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return rows

    return inner


class _CapturingConn:
    def __init__(self) -> None:
        self.sql = ""
        self.args: tuple[object, ...] = ()

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        self.sql = sql
        self.args = args
        return [{"fact": "Ranked fact", "category": "preference", "source": "test"}]
