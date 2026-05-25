"""Policy-gated skill runner.

SkillRunner is the narrow execution path every agent should use once it starts
calling concrete adapters. It does not know about Gmail, UniFi, MCP, or any
provider. It only knows how to:

1. ask SkillPolicyGate whether a call may proceed
2. return structured non-execution results for deny / approval-required
3. invoke the registered handler only after an allow decision
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol

from brain.skills.policy_gate import (
    SkillInvocation,
    SkillPolicyDecision,
    SkillPolicyGate,
)

SkillRunStatus = Literal["executed", "approval_required", "denied"]


@dataclass(frozen=True, slots=True)
class SkillCall:
    """Payload passed to a registered skill handler."""

    invocation: SkillInvocation
    decision: SkillPolicyDecision
    payload: Mapping[str, Any] = field(default_factory=dict)


class SkillHandler(Protocol):
    def __call__(self, call: SkillCall) -> Awaitable[Any] | Any:
        """Run the provider adapter for one already-authorized skill call."""


@dataclass(frozen=True, slots=True)
class SkillRunResult:
    """Structured result from SkillRunner.run()."""

    status: SkillRunStatus
    decision: SkillPolicyDecision
    output: Any = None

    @property
    def executed(self) -> bool:
        return self.status == "executed"

    @property
    def requires_approval(self) -> bool:
        return self.status == "approval_required"

    @property
    def denied(self) -> bool:
        return self.status == "denied"


class SkillRunner:
    """Run registered skill handlers behind SkillPolicyGate."""

    def __init__(
        self,
        *,
        gate: SkillPolicyGate | None = None,
        handlers: Mapping[str, SkillHandler] | None = None,
    ) -> None:
        self._gate = gate or SkillPolicyGate()
        self._handlers: dict[str, SkillHandler] = dict(handlers or {})

    def register(self, skill_name: str, handler: SkillHandler) -> None:
        self._handlers[skill_name] = handler

    async def run(
        self,
        conn: Any,
        invocation: SkillInvocation,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> SkillRunResult:
        decision = await self._gate.evaluate(conn, invocation)

        if decision.requires_approval:
            return SkillRunResult(status="approval_required", decision=decision)
        if not decision.allowed:
            return SkillRunResult(status="denied", decision=decision)

        handler = self._handlers.get(invocation.skill_name)
        if handler is None:
            return SkillRunResult(
                status="denied",
                decision=replace(
                    decision,
                    outcome="deny",
                    reason="adapter_not_registered",
                ),
            )

        output = handler(
            SkillCall(
                invocation=invocation,
                decision=decision,
                payload=dict(payload or {}),
            )
        )
        if inspect.isawaitable(output):
            output = await output

        return SkillRunResult(status="executed", decision=decision, output=output)
