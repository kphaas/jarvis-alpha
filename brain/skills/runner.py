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


class SkillApprovalBridgeProtocol(Protocol):
    async def find_approved(
        self,
        conn: Any,
        invocation: SkillInvocation,
        decision: SkillPolicyDecision,
        payload: Mapping[str, Any] | None,
    ) -> Any | None:
        """Return an approved queue item for this exact call, if present."""

    async def queue_required(
        self,
        conn: Any,
        invocation: SkillInvocation,
        decision: SkillPolicyDecision,
        payload: Mapping[str, Any] | None,
    ) -> Any:
        """Queue this call for approval and return the pending queue item."""

    async def consume(self, conn: Any, queue_id: str) -> None:
        """Mark an approved queue item executed after successful handler run."""


@dataclass(frozen=True, slots=True)
class SkillRunResult:
    """Structured result from SkillRunner.run()."""

    status: SkillRunStatus
    decision: SkillPolicyDecision
    output: Any = None
    approval_queue_id: str | None = None
    approval_status: str | None = None

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
        approval_bridge: SkillApprovalBridgeProtocol | None = None,
    ) -> None:
        self._gate = gate or SkillPolicyGate()
        self._handlers: dict[str, SkillHandler] = dict(handlers or {})
        self._approval_bridge = approval_bridge

    def register(self, skill_name: str, handler: SkillHandler) -> None:
        self._handlers[skill_name] = handler

    async def run(
        self,
        conn: Any,
        invocation: SkillInvocation,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> SkillRunResult:
        payload_dict = dict(payload or {})
        decision = await self._gate.evaluate(conn, invocation)
        handler = self._handlers.get(invocation.skill_name)

        if decision.requires_approval:
            if handler is None:
                return SkillRunResult(
                    status="denied",
                    decision=replace(
                        decision,
                        outcome="deny",
                        reason="adapter_not_registered",
                    ),
                )
            if self._approval_bridge is None:
                return SkillRunResult(status="approval_required", decision=decision)

            approved = await self._approval_bridge.find_approved(
                conn,
                invocation,
                decision,
                payload_dict,
            )
            if approved is None:
                queued = await self._approval_bridge.queue_required(
                    conn,
                    invocation,
                    decision,
                    payload_dict,
                )
                return SkillRunResult(
                    status="approval_required",
                    decision=decision,
                    approval_queue_id=str(queued.queue_id),
                    approval_status=str(queued.status),
                )

            approved_invocation = replace(invocation, approval_granted=True)
            approved_decision = await self._gate.evaluate(conn, approved_invocation)
            if approved_decision.requires_approval:
                return SkillRunResult(
                    status="approval_required",
                    decision=approved_decision,
                    approval_queue_id=str(approved.queue_id),
                    approval_status="approved_unusable",
                )
            if not approved_decision.allowed:
                return SkillRunResult(
                    status="denied",
                    decision=approved_decision,
                    approval_queue_id=str(approved.queue_id),
                    approval_status="approved_unusable",
                )

            result = await self._execute_handler(
                handler,
                approved_invocation,
                approved_decision,
                payload_dict,
            )
            await self._approval_bridge.consume(conn, str(approved.queue_id))
            return SkillRunResult(
                status="executed",
                decision=approved_decision,
                output=result,
                approval_queue_id=str(approved.queue_id),
                approval_status="approved_consumed",
            )

        if not decision.allowed:
            return SkillRunResult(status="denied", decision=decision)

        if handler is None:
            return SkillRunResult(
                status="denied",
                decision=replace(
                    decision,
                    outcome="deny",
                    reason="adapter_not_registered",
                ),
            )

        output = await self._execute_handler(
            handler, invocation, decision, payload_dict
        )
        return SkillRunResult(status="executed", decision=decision, output=output)

    async def _execute_handler(
        self,
        handler: SkillHandler,
        invocation: SkillInvocation,
        decision: SkillPolicyDecision,
        payload: Mapping[str, Any],
    ) -> Any:
        output = handler(
            SkillCall(
                invocation=invocation,
                decision=decision,
                payload=dict(payload),
            )
        )
        if inspect.isawaitable(output):
            output = await output

        return output
