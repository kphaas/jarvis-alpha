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
    monkeypatch.setattr(MemoryService, "_get_graph", _async_rows([]))
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
    monkeypatch.setattr(MemoryService, "_get_graph", _async_rows([]))
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
    monkeypatch.setattr(MemoryService, "_get_graph", _async_rows([]))
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
async def test_build_context_injects_temporal_graph_before_episodic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(memory_module, "fetch_personality_memory", _async_rows([]))
    monkeypatch.setattr(
        memory_module,
        "load_spark_memory_grounding",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        MemoryService,
        "_get_semantic",
        _async_rows([{"fact": "Stable memory fact."}]),
    )
    monkeypatch.setattr(
        MemoryService,
        "_get_graph",
        _async_rows(
            [
                {
                    "item_type": "node",
                    "kind": "project",
                    "label_preview": "Temporal graph memory",
                    "source": "operator",
                    "confidence": 0.93,
                    "retrieval_state": "current",
                },
                {
                    "item_type": "edge",
                    "kind": "works_on",
                    "label_preview": "Ken works on Memory",
                    "source": "dream",
                    "confidence": 0.81,
                    "retrieval_state": "historical",
                },
            ]
        ),
    )
    monkeypatch.setattr(
        MemoryService,
        "_get_episodic",
        _async_rows([{"summary": "Relevant prior turn."}]),
    )
    monkeypatch.setattr(MemoryService, "_get_working", _async_rows([]))

    context = await MemoryService().build_context(
        conn=object(),
        user_id=uuid4(),
        prompt="What is our memory graph plan?",
        session_id="thread-1",
        embedding=[0.1],
        principal_id="ken",
    )

    assert "[TEMPORAL GRAPH]" in context
    assert "Use [current] rows as present facts." in context
    assert "- [current] Project: Temporal graph memory" in context
    assert "- [historical] Relation: Ken works on Memory" in context
    assert context.index("[ALWAYS KNOWN]") < context.index("[TEMPORAL GRAPH]")
    assert context.index("[TEMPORAL GRAPH]") < context.index("[RELEVANT PAST]")


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


@pytest.mark.asyncio
async def test_temporal_graph_memory_uses_prompt_relevance_and_bounds() -> None:
    conn = _GraphCapturingConn()
    user_id = uuid4()

    rows = await MemoryService()._get_graph(
        conn,
        user_id,
        prompt="Memory graph projects",
    )

    assert rows == [
        {
            "item_type": "node",
            "kind": "project",
            "label_preview": "Temporal graph memory",
            "source": "operator",
            "confidence": 0.9,
        }
    ]
    assert "alpha_memory_graph_nodes" in conn.sql
    assert "alpha_memory_graph_edges" in conn.sql
    assert "plainto_tsquery" in conn.sql
    assert "retrieval_score" in conn.sql
    assert "retrieval_state" in conn.sql
    assert "$5::boolean" in conn.sql
    assert conn.args == (user_id, "Memory graph projects", 8, 8, False, 90)


@pytest.mark.asyncio
async def test_temporal_graph_history_prompts_opt_into_historical_rows() -> None:
    conn = _GraphCapturingConn()
    user_id = uuid4()

    await MemoryService()._get_graph(
        conn,
        user_id,
        prompt="What changed in the old trip plan?",
    )

    assert conn.args == (user_id, "What changed in the old trip plan?", 8, 8, True, 90)


def test_graph_context_line_labels_currentness() -> None:
    assert (
        MemoryService._graph_context_line(
            {
                "item_type": "node",
                "kind": "project",
                "label_preview": "Seattle trip",
                "source": "spark",
                "confidence": 0.88,
                "retrieval_state": "needs_refresh",
            }
        )
        == "- [needs refresh] Project: Seattle trip (confidence 0.88, source spark)"
    )

    assert (
        MemoryService._graph_context_line(
            {
                "item_type": "edge",
                "kind": "planned_with",
                "label_preview": "Ken planned with Sweta",
                "source": "dream",
                "confidence": 0.74,
                "retrieval_state": "historical",
            }
        )
        == "- [historical] Relation: Ken planned with Sweta (planned with, confidence 0.74, source dream)"
    )


@pytest.mark.parametrize(
    ("prompt", "include_history"),
    [
        ("What is the current trip plan?", False),
        ("What is the latest project state?", False),
        ("What is our upcoming trip plan?", False),
        ("What is the next planned project?", False),
        ("What are the current changes to the trip plan?", False),
        ("What are my priorities for memory?", False),
        ("What changed?", True),
        ("What changed in the old trip plan?", True),
        ("What changed before this current plan?", True),
        ("Show the relationship timeline.", True),
        ("How did this relationship evolve?", True),
        ("What did this use to be?", True),
        ("Show stale relationship history.", True),
    ],
)
def test_temporal_graph_history_classifier_separates_current_from_old(
    prompt: str,
    include_history: bool,
) -> None:
    assert MemoryService._include_historical_graph(prompt) is include_history


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


class _GraphCapturingConn:
    def __init__(self) -> None:
        self.sql = ""
        self.args: tuple[object, ...] = ()

    async def fetch(self, sql: str, *args: object) -> list[dict[str, object]]:
        self.sql = sql
        self.args = args
        return [
            {
                "item_type": "node",
                "kind": "project",
                "label_preview": "Temporal graph memory",
                "source": "operator",
                "confidence": 0.9,
            }
        ]
