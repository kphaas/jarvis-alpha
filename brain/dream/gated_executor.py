"""Approval-gated execution planning for Dream write-capable steps."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from brain.dream.read_only_executor import is_read_only_tool_step
from brain.middleware.approval_classes import determine_risk_tier

VERIFICATION_PREFIX = "dream_write_gate_v1:"

HIGH_RISK_TERMS = (
    "admin",
    "auth",
    "bypassrls",
    "delete",
    "destroy",
    "drop",
    "force rls",
    "grant",
    "key",
    "kill",
    "launchagent",
    "medical",
    "pki",
    "revoke",
    "rls",
    "role",
    "secret",
    "shutdown",
    "sloane",
    "token",
    "truncate",
)

DEPLOY_TERMS = (
    "commit",
    "deploy",
    "merge",
    "migration",
    "pull",
    "push",
    "restart",
    "schema",
    "scp",
)

CHILD_FACING_TERMS = (
    "child",
    "children",
    "custody",
    "family",
    "ryleigh",
    "sloane",
)

WRITE_TERMS = (
    "apply",
    "create",
    "edit",
    "execute",
    "fix",
    "install",
    "modify",
    "patch",
    "publish",
    "rotate",
    "run",
    "start",
    "stop",
    "update",
    "write",
)


@dataclass(frozen=True)
class DreamStepApprovalPlan:
    step_id: int
    step_index: int
    name: str
    action_classes: list[str]
    risk_tier: str
    parameters_hash: str
    reason: str
    requires_post_action_verification: bool = True
    requires_compensation_metadata: bool = True


def _step_text(step: Mapping[str, Any]) -> str:
    return " ".join(str(step.get(key) or "") for key in ("name", "description"))


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _stable_step_payload(step: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "session_id": step.get("session_id"),
        "step_id": step.get("id"),
        "step_index": step.get("step_index"),
        "name": step.get("name"),
        "description": step.get("description"),
        "agent_type": step.get("agent_type"),
        "depends_on": list(step.get("depends_on") or []),
    }


def _hash_step(step: Mapping[str, Any]) -> str:
    payload = json.dumps(_stable_step_payload(step), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def approval_parameters_hash_for_step(step: Mapping[str, Any]) -> str:
    """Return the approval hash for a persisted Dream step."""
    return _hash_step(step)


def _at_least_t4(action_classes: list[str]) -> str:
    tier = determine_risk_tier(action_classes)
    if tier in {"T1", "T2", "T3"}:
        return "T4"
    return tier


def build_write_approval_plan(step: Mapping[str, Any]) -> DreamStepApprovalPlan | None:
    """Classify a non-read-only Dream step for human approval.

    The first production-safe write-capable executor slice does not run the
    action. It records the approval gate, blocks the step, and requires a later
    allowlisted executor to prove verification and compensation metadata.
    """

    if is_read_only_tool_step(step):
        return None

    text = _step_text(step).lower().replace("_", " ")
    agent_type = str(step.get("agent_type") or "unknown")
    action_classes = ["write", "dream_autonomous"]
    reasons: list[str] = ["autonomous_dream_write_gate"]

    if agent_type in {"llm", "cloud"}:
        action_classes.extend(["external_call", "cost_incurring"])
        reasons.append(f"{agent_type}_execution_disabled_until_approved")
    elif agent_type == "code":
        action_classes.append("code_execution")
        reasons.append("code_execution_disabled_until_approved")
    elif agent_type not in {"tool", "canary"}:
        action_classes.append("unclassified")
        reasons.append(f"unsupported_agent_type:{agent_type}")

    if _contains_any(text, HIGH_RISK_TERMS):
        action_classes.append("admin")
        reasons.append("high_risk_term")
    if _contains_any(text, DEPLOY_TERMS):
        action_classes.append("deploy")
        reasons.append("deploy_or_schema_term")
    if _contains_any(text, CHILD_FACING_TERMS):
        action_classes.append("child_facing")
        reasons.append("child_or_family_term")
    if _contains_any(text, WRITE_TERMS):
        reasons.append("write_term")

    deduped_classes = list(dict.fromkeys(action_classes))
    risk_tier = _at_least_t4(deduped_classes)
    if "admin" in deduped_classes:
        risk_tier = "T5"

    step_id = int(step["id"])
    step_index = int(step["step_index"])
    return DreamStepApprovalPlan(
        step_id=step_id,
        step_index=step_index,
        name=str(step.get("name") or f"step_{step_index}"),
        action_classes=deduped_classes,
        risk_tier=risk_tier,
        parameters_hash=_hash_step(step),
        reason=",".join(dict.fromkeys(reasons)),
        requires_compensation_metadata=risk_tier == "T5"
        or "deploy" in deduped_classes
        or "admin" in deduped_classes,
    )


def encode_gate_verification(queue_id: str, plan: DreamStepApprovalPlan) -> str:
    payload = {
        "queue_id": queue_id,
        "risk_tier": plan.risk_tier,
        "action_classes": plan.action_classes,
        "requires_post_action_verification": plan.requires_post_action_verification,
        "requires_compensation_metadata": plan.requires_compensation_metadata,
    }
    return VERIFICATION_PREFIX + json.dumps(payload, sort_keys=True)


def decode_gate_verification(value: object) -> dict[str, Any] | None:
    if not isinstance(value, str) or not value.startswith(VERIFICATION_PREFIX):
        return None
    try:
        return json.loads(value[len(VERIFICATION_PREFIX) :])
    except json.JSONDecodeError:
        return None
