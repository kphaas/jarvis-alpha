"""Read-only execution helpers for persisted Dream plans."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping


READ_ONLY_VERBS = (
    "check",
    "inspect",
    "list",
    "read",
    "summarize",
    "validate",
    "verify",
)
WRITE_TERMS = (
    "alter",
    "apply",
    "commit",
    "create",
    "delete",
    "deploy",
    "drop",
    "edit",
    "install",
    "kill",
    "merge",
    "modify",
    "patch",
    "push",
    "remove",
    "restart",
    "rotate",
    "run migration",
    "scp",
    "signal",
    "start",
    "stop",
    "update",
    "write",
)


@dataclass(frozen=True)
class ReadOnlyExecutionResult:
    status: str
    reason: str
    output_summary: str | None = None
    verification: str | None = None
    input_hash: str | None = None


def _text(step: Mapping) -> str:
    return " ".join(str(step.get(key) or "") for key in ("name", "description")).strip()


def is_read_only_tool_step(step: Mapping) -> bool:
    agent_type = step.get("agent_type")
    if agent_type not in ("tool", "canary"):
        return False
    text = _text(step).lower().replace("_", " ")
    if not any(verb in text for verb in READ_ONLY_VERBS):
        return False
    return not any(term in text for term in WRITE_TERMS)


def execute_read_only_step(step: Mapping) -> ReadOnlyExecutionResult:
    """Execute the first safe slice: validate and record read-only tool work.

    This intentionally does not invoke shell, network, database mutation beyond
    the Dream step audit row, or LLMs. Write-capable execution comes later behind
    approval and kill-switch gates.
    """

    text = _text(step)
    input_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    agent_type = step.get("agent_type")
    if agent_type not in ("tool", "canary"):
        return ReadOnlyExecutionResult(
            status="skipped",
            reason=f"unsupported_agent_type:{agent_type}",
        )
    if not is_read_only_tool_step(step):
        return ReadOnlyExecutionResult(
            status="skipped",
            reason="not_read_only_allowlisted",
        )
    name = str(step.get("name") or "unnamed_step")
    return ReadOnlyExecutionResult(
        status="completed",
        reason="read_only_allowlisted",
        output_summary=(
            f"Read-only Dream step acknowledged: {name}. "
            "No write-capable tool, shell command, network mutation, or LLM call was invoked."
        ),
        verification="read_only_executor_v1",
        input_hash=input_hash,
    )
