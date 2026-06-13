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
async def test_build_context_degrades_when_spark_grounding_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_loader(**_kwargs: object) -> None:
        raise RuntimeError("vault missing")

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


def _async_rows(rows: list[dict[str, object]]):
    async def inner(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return rows

    return inner
