"""Approval queue bridge for high-risk SkillRunner calls."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from asyncpg.exceptions import UniqueViolationError

from brain.skills.policy_gate import SkillInvocation, SkillPolicyDecision
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")

SkillApprovalStatus = Literal["pending", "approved"]
ApprovalNotifier = Callable[..., Awaitable[bool]]
_DEFAULT_NOTIFIER = object()


@dataclass(frozen=True, slots=True)
class SkillApprovalItem:
    queue_id: str
    status: SkillApprovalStatus
    parameters_hash: str


class SkillApprovalBridge:
    """Connect SkillRunner T4/T5 decisions to the existing approval queue.

    The first high-risk skill call queues a deterministic approval item. After
    the operator approves it in the existing Approvals UI, the agent must retry
    the exact same skill call. SkillRunner then consumes the approved queue row
    only after the handler executes successfully.
    """

    def __init__(
        self,
        *,
        notifier: ApprovalNotifier | None | object = _DEFAULT_NOTIFIER,
    ) -> None:
        self._notifier = notifier

    async def find_approved(
        self,
        conn: Any,
        invocation: SkillInvocation,
        decision: SkillPolicyDecision,
        payload: Mapping[str, Any] | None,
    ) -> SkillApprovalItem | None:
        parameters_hash = skill_parameters_hash(invocation, decision, payload)
        row = await _approval_queue_row(
            conn,
            actor_sub=_actor_sub(invocation),
            parameters_hash=parameters_hash,
            status="approved",
        )
        if row is None:
            return None
        return SkillApprovalItem(
            queue_id=str(row["id"]),
            status="approved",
            parameters_hash=parameters_hash,
        )

    async def queue_required(
        self,
        conn: Any,
        invocation: SkillInvocation,
        decision: SkillPolicyDecision,
        payload: Mapping[str, Any] | None,
    ) -> SkillApprovalItem:
        parameters_hash = skill_parameters_hash(invocation, decision, payload)
        actor_sub = _actor_sub(invocation)

        existing = await _approval_queue_row(
            conn,
            actor_sub=actor_sub,
            parameters_hash=parameters_hash,
            status="pending",
        )
        if existing is not None:
            return SkillApprovalItem(
                queue_id=str(existing["id"]),
                status="pending",
                parameters_hash=parameters_hash,
            )

        action_classes = _action_classes(invocation)
        queue_id = await self._enqueue(
            conn,
            action_classes=action_classes,
            tier=decision.approval_tier or "T4",
            actor_sub=actor_sub,
            description=_description(invocation),
            parameters_hash=parameters_hash,
        )

        notifier = self._resolve_notifier()
        if notifier is not None:
            try:
                await notifier(
                    queue_id=queue_id,
                    tier=decision.approval_tier or "T4",
                    action_classes=action_classes,
                    method="SKILL",
                    path=invocation.skill_name,
                    actor_sub=actor_sub,
                    actor_type="agent",
                )
            except Exception:
                logger.error(
                    "skill approval notification failed agent_id=%s skill_name=%s",
                    invocation.agent_id,
                    invocation.skill_name,
                    exc_info=True,
                )

        return SkillApprovalItem(
            queue_id=queue_id,
            status="pending",
            parameters_hash=parameters_hash,
        )

    def _resolve_notifier(self) -> ApprovalNotifier | None:
        if self._notifier is None:
            return None
        if self._notifier is not _DEFAULT_NOTIFIER:
            return self._notifier

        from brain.services.approval_notifier import send_approval_notification

        return send_approval_notification

    async def consume(self, conn: Any, queue_id: str) -> None:
        await conn.execute(
            "SELECT public.consume_approved_queue_item($1::uuid)",
            queue_id,
        )

    async def _enqueue(
        self,
        conn: Any,
        *,
        action_classes: list[str],
        tier: str,
        actor_sub: str,
        description: str,
        parameters_hash: str,
    ) -> str:
        nonce = uuid4().hex
        try:
            queue_id = await conn.fetchval(
                """SELECT public.enqueue_approval_request(
                       $1::text[], $2, $3, $4, $5, $6, $7
                   )""",
                action_classes,
                tier,
                actor_sub,
                "agent",
                description,
                parameters_hash,
                nonce,
            )
            return str(queue_id)
        except UniqueViolationError:
            existing = await _approval_queue_row(
                conn,
                actor_sub=actor_sub,
                parameters_hash=parameters_hash,
                status="pending",
            )
            if existing is not None:
                return str(existing["id"])
            raise


def skill_parameters_hash(
    invocation: SkillInvocation,
    decision: SkillPolicyDecision,
    payload: Mapping[str, Any] | None,
) -> str:
    """Return stable, non-reversible identity for one skill approval request."""

    canonical = {
        "bridge_version": 1,
        "agent_id": invocation.agent_id,
        "skill_name": invocation.skill_name,
        "approval_tier": decision.approval_tier,
        "skill_scope": decision.skill_scope,
        "idempotency_key": invocation.idempotency_key,
        "body_access": invocation.body_access,
        "estimated_cost_usd": str(invocation.estimated_cost_usd),
        "payload": _normalize_payload(payload or {}),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


async def _approval_queue_row(
    conn: Any,
    *,
    actor_sub: str,
    parameters_hash: str,
    status: str,
) -> Any | None:
    async with conn.transaction():
        await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
        return await conn.fetchrow(
            """SELECT id
               FROM public.alpha_approval_queue
              WHERE actor_sub = $1
                AND parameters_hash = $2
                AND status = $3
                AND expires_at > NOW()
              ORDER BY requested_at DESC
              LIMIT 1""",
            actor_sub,
            parameters_hash,
            status,
        )


def _normalize_payload(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_payload(val)
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
            if not str(key).startswith("_")
        }
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize_payload(item) for item in value]
    return str(value)


def _actor_sub(invocation: SkillInvocation) -> str:
    return f"agent:{invocation.agent_id}"


def _description(invocation: SkillInvocation) -> str:
    return f"Agent {invocation.agent_id} requests skill {invocation.skill_name}"


def _action_classes(invocation: SkillInvocation) -> list[str]:
    classes = ["agent_skill"]
    if invocation.agent_id == "dream_mode":
        classes.append("dream_autonomous")
    return classes
