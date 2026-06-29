"""Deterministic memory context and management contract evals.

These checks stay offline. They guard the operator-visible guarantees that
matter for memory: safe archive semantics, current-vs-historical graph recall,
and stable context section ordering before Ask receives memory.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import inspect

from brain.memory.memory import MemoryService
from brain.routes import memory as memory_routes


@dataclass(frozen=True)
class MemoryContextEvalResult:
    name: str
    eval_group: str
    passed: bool
    details: dict[str, object]
    failures: tuple[str, ...] = ()


def run_memory_context_evals() -> list[MemoryContextEvalResult]:
    """Run deterministic memory production-readiness evals."""
    return [
        _semantic_delete_archives_contract(),
        _forget_scope_contract(),
        _current_prompt_excludes_history(),
        _historical_prompt_includes_history(),
        _change_prompt_includes_history(),
        _at0_prompt_includes_system_principal(),
        _graph_current_line_contract(),
        _graph_historical_edge_line_contract(),
        _context_section_order_contract(),
    ]


def memory_context_eval_payload() -> dict[str, object]:
    """Return a JSON-safe payload for scripts, CI, and deploy smokes."""
    results = run_memory_context_evals()
    failed = [result for result in results if not result.passed]
    return {
        "suite": "memory_context",
        "suite_version": 1,
        "status": "failed" if failed else "passed",
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "case_groups": _group_summary(results),
        "results": [
            {
                **asdict(result),
                "failures": list(result.failures),
            }
            for result in results
        ],
    }


def _semantic_delete_archives_contract() -> MemoryContextEvalResult:
    source = inspect.getsource(memory_routes.delete_semantic_memory)
    failures: list[str] = []
    if 'action="archive"' not in source:
        failures.append("delete_endpoint_does_not_archive")
    if 'note="user_deleted"' not in source:
        failures.append("delete_endpoint_missing_user_deleted_note")

    return MemoryContextEvalResult(
        name="semantic_delete_archives",
        eval_group="user_visible_management",
        passed=not failures,
        details={
            "endpoint": "DELETE /v1/memory/semantic/{memory_id}",
            "expected_behavior": "archive_semantic_row",
        },
        failures=tuple(failures),
    )


def _forget_scope_contract() -> MemoryContextEvalResult:
    source = inspect.getsource(memory_routes.forget_memory)
    failures: list[str] = []
    if "forget_by_topic" not in source:
        failures.append("missing_topic_delete_scope")
    if "forget_working" not in source:
        failures.append("missing_working_delete_scope")
    if "if body.topic:" not in source or "elif body.working_only:" not in source:
        failures.append("missing_topic_or_working_guard")

    return MemoryContextEvalResult(
        name="forget_requires_topic_or_working_scope",
        eval_group="user_visible_management",
        passed=not failures,
        details={
            "endpoint": "POST /v1/memory/forget",
            "expected_behavior": "bounded_forget_scope",
        },
        failures=tuple(failures),
    )


def _current_prompt_excludes_history() -> MemoryContextEvalResult:
    prompt = "What is Ken currently working on in memory?"
    include_history = MemoryService._include_historical_graph(prompt)
    return MemoryContextEvalResult(
        name="current_prompt_excludes_historical_graph",
        eval_group="auto_context",
        passed=include_history is False,
        details={"prompt": prompt, "include_history": include_history},
        failures=()
        if include_history is False
        else ("current_prompt_includes_history",),
    )


def _historical_prompt_includes_history() -> MemoryContextEvalResult:
    prompt = "Show the old memory project history."
    include_history = MemoryService._include_historical_graph(prompt)
    return MemoryContextEvalResult(
        name="historical_prompt_includes_historical_graph",
        eval_group="auto_context",
        passed=include_history is True,
        details={"prompt": prompt, "include_history": include_history},
        failures=()
        if include_history is True
        else ("historical_prompt_excludes_history",),
    )


def _change_prompt_includes_history() -> MemoryContextEvalResult:
    prompt = "What changed about the Helm memory graph?"
    include_history = MemoryService._include_historical_graph(prompt)
    return MemoryContextEvalResult(
        name="change_prompt_includes_historical_graph",
        eval_group="auto_context",
        passed=include_history is True,
        details={"prompt": prompt, "include_history": include_history},
        failures=() if include_history is True else ("change_prompt_excludes_history",),
    )


def _at0_prompt_includes_system_principal() -> MemoryContextEvalResult:
    prompt = "What can AT-0 Memory and Helm do?"
    include_system = MemoryService._include_at0_system_graph(prompt)
    return MemoryContextEvalResult(
        name="at0_prompt_includes_system_principal",
        eval_group="auto_context",
        passed=include_system is True,
        details={"prompt": prompt, "include_at0_system_graph": include_system},
        failures=()
        if include_system is True
        else ("at0_system_principal_not_selected",),
    )


def _graph_current_line_contract() -> MemoryContextEvalResult:
    line = MemoryService._graph_context_line(
        {
            "item_type": "node",
            "kind": "person",
            "label_preview": "Ken Haas",
            "source": "explicit",
            "confidence": 0.92,
            "retrieval_state": "current",
        }
    )
    failures: list[str] = []
    if "[current]" not in line:
        failures.append("missing_current_label")
    if "confidence 0.92" not in line:
        failures.append("missing_confidence")

    return MemoryContextEvalResult(
        name="graph_current_line_is_labeled",
        eval_group="auto_context",
        passed=not failures,
        details={"line": line},
        failures=tuple(failures),
    )


def _graph_historical_edge_line_contract() -> MemoryContextEvalResult:
    line = MemoryService._graph_context_line(
        {
            "item_type": "edge",
            "kind": "worked_on",
            "label_preview": "Ken worked on Old Project",
            "source": "operator",
            "confidence": 0.81,
            "retrieval_state": "historical",
        }
    )
    failures: list[str] = []
    if "[historical]" not in line:
        failures.append("missing_historical_label")
    if "Relation:" not in line:
        failures.append("missing_relation_marker")

    return MemoryContextEvalResult(
        name="graph_historical_edge_is_labeled",
        eval_group="auto_context",
        passed=not failures,
        details={"line": line},
        failures=tuple(failures),
    )


def _context_section_order_contract() -> MemoryContextEvalResult:
    source = inspect.getsource(MemoryService.build_context)
    expected_order = [
        "spark_grounding",
        "[ALWAYS KNOWN]",
        "[TEMPORAL GRAPH]",
        "[RELEVANT PAST]",
        "[RECENT CONVERSATION]",
    ]
    positions = {needle: source.find(needle) for needle in expected_order}
    failures: list[str] = [
        f"missing:{needle}" for needle, position in positions.items() if position < 0
    ]
    if not failures:
        ordered_positions = [positions[needle] for needle in expected_order]
        if ordered_positions != sorted(ordered_positions):
            failures.append("context_sections_out_of_order")

    return MemoryContextEvalResult(
        name="context_sections_are_ordered_for_ask",
        eval_group="auto_context",
        passed=not failures,
        details={"expected_order": expected_order, "positions": positions},
        failures=tuple(failures),
    )


def _group_summary(results: list[MemoryContextEvalResult]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for result in results:
        group = summary.setdefault(
            result.eval_group, {"case_count": 0, "passed": 0, "failed": 0}
        )
        group["case_count"] += 1
        group["passed" if result.passed else "failed"] += 1
    return summary
