"""Bounded rollout policy for outcome-calibrated chat routing."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
import os
from typing import Literal

from brain.routing.model_capability_registry import (
    DEFAULT_CHAT_MODEL_CAPABILITIES,
    ChatModelCapability,
    ChatTaskClass,
    select_chat_model_for_task,
    task_class_for_complexity,
)
from brain.routing.model_score_calibration import (
    MIN_CALIBRATION_SAMPLES,
    chat_model_score_calibration_payload,
)
from brain.routing.complexity import score

CHAT_CALIBRATED_ROUTING_ROLLOUT_VERSION = "chat_calibrated_routing_rollout.v1"
CHAT_CALIBRATED_ROUTING_METADATA_KEYS = (
    "chat_calibrated_routing_schema_version",
    "chat_calibrated_routing_mode",
    "chat_calibrated_routing_applied",
    "chat_calibrated_routing_reason",
    "chat_calibrated_routing_task_class",
    "chat_calibrated_routing_baseline_route",
    "chat_calibrated_routing_candidate_route",
    "chat_calibrated_routing_baseline_samples",
    "chat_calibrated_routing_candidate_samples",
    "chat_calibrated_routing_min_samples",
    "chat_calibrated_routing_max_score_delta",
    "chat_calibrated_routing_rollout_percent",
    "chat_calibrated_routing_rollout_bucket",
    "chat_calibrated_routing_rollback_samples",
    "chat_calibrated_routing_rollback_accept_rate",
)

CalibratedRoutingMode = Literal["off", "shadow", "active"]
_ALLOWED_MODES = frozenset({"off", "shadow", "active"})


@dataclass(frozen=True)
class ChatCalibratedRoutingPolicy:
    mode: CalibratedRoutingMode = "off"
    min_samples: int = 10
    max_score_delta: int = 5
    rollout_percent: int = 0
    rollback_min_samples: int = 5
    rollback_accept_rate: float = 0.6
    configuration_valid: bool = True

    @classmethod
    def from_env(cls) -> ChatCalibratedRoutingPolicy:
        raw_mode = os.getenv("ALPHA_CHAT_CALIBRATED_ROUTING_MODE", "off").lower()
        mode_valid = raw_mode in _ALLOWED_MODES
        mode: CalibratedRoutingMode = "off"
        if raw_mode == "shadow":
            mode = "shadow"
        elif raw_mode == "active":
            mode = "active"
        min_samples, min_samples_valid = _bounded_int_env(
            "ALPHA_CHAT_CALIBRATED_ROUTING_MIN_SAMPLES",
            default=10,
            minimum=MIN_CALIBRATION_SAMPLES,
            maximum=100,
        )
        max_delta, max_delta_valid = _bounded_int_env(
            "ALPHA_CHAT_CALIBRATED_ROUTING_MAX_SCORE_DELTA",
            default=5,
            minimum=1,
            maximum=10,
        )
        rollout_percent, rollout_valid = _bounded_int_env(
            "ALPHA_CHAT_CALIBRATED_ROUTING_PERCENT",
            default=0,
            minimum=0,
            maximum=100,
        )
        rollback_min, rollback_min_valid = _bounded_int_env(
            "ALPHA_CHAT_CALIBRATED_ROUTING_ROLLBACK_MIN_SAMPLES",
            default=5,
            minimum=1,
            maximum=100,
        )
        rollback_rate, rollback_rate_valid = _bounded_float_env(
            "ALPHA_CHAT_CALIBRATED_ROUTING_ROLLBACK_ACCEPT_RATE",
            default=0.6,
            minimum=0.0,
            maximum=1.0,
        )
        configuration_valid = all(
            (
                mode_valid,
                min_samples_valid,
                max_delta_valid,
                rollout_valid,
                rollback_min_valid,
                rollback_rate_valid,
            )
        )
        return cls(
            mode=mode if configuration_valid else "off",
            min_samples=min_samples,
            max_score_delta=max_delta,
            rollout_percent=rollout_percent,
            rollback_min_samples=rollback_min,
            rollback_accept_rate=rollback_rate,
            configuration_valid=configuration_valid,
        )


@dataclass(frozen=True)
class ChatCalibratedRoutingDecision:
    mode: CalibratedRoutingMode
    applied: bool
    reason: str
    task_class: ChatTaskClass
    baseline_route_mode: str
    candidate_route_mode: str
    baseline_samples: int
    candidate_samples: int
    min_samples: int
    max_score_delta: int
    rollout_percent: int
    rollout_bucket: int | None
    rollback_samples: int
    rollback_accept_rate: float | None
    routing_capabilities: tuple[ChatModelCapability, ...]

    def metadata(self) -> dict[str, object]:
        return {
            "chat_calibrated_routing_schema_version": (
                CHAT_CALIBRATED_ROUTING_ROLLOUT_VERSION
            ),
            "chat_calibrated_routing_mode": self.mode,
            "chat_calibrated_routing_applied": self.applied,
            "chat_calibrated_routing_reason": self.reason,
            "chat_calibrated_routing_task_class": self.task_class,
            "chat_calibrated_routing_baseline_route": self.baseline_route_mode,
            "chat_calibrated_routing_candidate_route": self.candidate_route_mode,
            "chat_calibrated_routing_baseline_samples": self.baseline_samples,
            "chat_calibrated_routing_candidate_samples": self.candidate_samples,
            "chat_calibrated_routing_min_samples": self.min_samples,
            "chat_calibrated_routing_max_score_delta": self.max_score_delta,
            "chat_calibrated_routing_rollout_percent": self.rollout_percent,
            "chat_calibrated_routing_rollout_bucket": self.rollout_bucket,
            "chat_calibrated_routing_rollback_samples": self.rollback_samples,
            "chat_calibrated_routing_rollback_accept_rate": (self.rollback_accept_rate),
        }


def calibrated_routing_observation_enabled(
    policy: ChatCalibratedRoutingPolicy | None = None,
) -> bool:
    selected = policy or ChatCalibratedRoutingPolicy.from_env()
    return selected.configuration_valid and selected.mode in {"shadow", "active"}


def plan_calibrated_routing(
    *,
    prompt: str,
    outcomes: Sequence[Mapping[str, object]] = (),
    rollout_key: str | None = None,
    policy: ChatCalibratedRoutingPolicy | None = None,
    capabilities: tuple[ChatModelCapability, ...] = DEFAULT_CHAT_MODEL_CAPABILITIES,
) -> ChatCalibratedRoutingDecision:
    selected_policy = policy or ChatCalibratedRoutingPolicy.from_env()
    task_class = task_class_for_complexity(score(prompt))
    baseline = select_chat_model_for_task(task_class, capabilities=capabilities)
    decision = ChatCalibratedRoutingDecision(
        mode=selected_policy.mode,
        applied=False,
        reason="",
        task_class=task_class,
        baseline_route_mode=baseline.route_mode,
        candidate_route_mode=baseline.route_mode,
        baseline_samples=0,
        candidate_samples=0,
        min_samples=selected_policy.min_samples,
        max_score_delta=selected_policy.max_score_delta,
        rollout_percent=selected_policy.rollout_percent,
        rollout_bucket=None,
        rollback_samples=0,
        rollback_accept_rate=None,
        routing_capabilities=capabilities,
    )
    if not selected_policy.configuration_valid:
        return replace(decision, reason="invalid_policy_fail_closed")
    if selected_policy.mode == "off":
        return replace(decision, reason="rollout_disabled")

    payload = chat_model_score_calibration_payload(
        outcomes,
        capabilities=capabilities,
    )
    rows = {
        str(row.get("route_mode")): row
        for row in payload.get("calibrated_models", [])
        if isinstance(row, Mapping)
    }
    bounded_capabilities = _bounded_capabilities(
        capabilities,
        rows=rows,
        min_samples=selected_policy.min_samples,
        max_score_delta=selected_policy.max_score_delta,
    )
    candidate = select_chat_model_for_task(
        task_class,
        capabilities=bounded_capabilities,
    )
    baseline_samples = _sample_count(rows.get(baseline.route_mode))
    candidate_samples = _sample_count(rows.get(candidate.route_mode))
    rollback_samples, rollback_accept_rate = _applied_rollout_stats(outcomes)
    evaluated = replace(
        decision,
        candidate_route_mode=candidate.route_mode,
        baseline_samples=baseline_samples,
        candidate_samples=candidate_samples,
        rollback_samples=rollback_samples,
        rollback_accept_rate=rollback_accept_rate,
    )

    routes_ready = min(baseline_samples, candidate_samples) >= (
        selected_policy.min_samples
    )
    if selected_policy.mode == "shadow":
        return replace(
            evaluated,
            reason=(
                "shadow_candidate_ready"
                if routes_ready
                else "shadow_insufficient_samples"
            ),
        )
    if (
        rollback_accept_rate is not None
        and rollback_samples >= selected_policy.rollback_min_samples
        and rollback_accept_rate < selected_policy.rollback_accept_rate
    ):
        return replace(evaluated, reason="rollback_accept_rate_breached")
    if not routes_ready:
        return replace(evaluated, reason="insufficient_route_samples")
    if candidate.route_mode == baseline.route_mode:
        return replace(evaluated, reason="candidate_matches_baseline")
    if selected_policy.rollout_percent == 0:
        return replace(evaluated, reason="rollout_percentage_zero")
    if not rollout_key:
        return replace(evaluated, reason="missing_rollout_key")

    bucket = _rollout_bucket(rollout_key)
    with_bucket = replace(evaluated, rollout_bucket=bucket)
    if bucket > selected_policy.rollout_percent:
        return replace(with_bucket, reason="outside_rollout_percentage")
    return replace(
        with_bucket,
        applied=True,
        reason="calibrated_route_selected",
        routing_capabilities=bounded_capabilities,
    )


def calibrated_routing_rollout_metrics(
    outcomes: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    observed = [
        outcome
        for outcome in outcomes
        if outcome.get("chat_calibrated_routing_schema_version")
        == CHAT_CALIBRATED_ROUTING_ROLLOUT_VERSION
    ]
    applied = [
        outcome
        for outcome in observed
        if outcome.get("chat_calibrated_routing_applied") is True
    ]
    reasons = Counter(
        str(outcome.get("chat_calibrated_routing_reason") or "unknown")
        for outcome in observed
    )
    modes = Counter(
        str(outcome.get("chat_calibrated_routing_mode") or "unknown")
        for outcome in observed
    )
    return {
        "schema_version": CHAT_CALIBRATED_ROUTING_ROLLOUT_VERSION,
        "observed_outcome_count": len(observed),
        "applied_outcome_count": len(applied),
        "apply_rate": round(len(applied) / len(observed), 3) if observed else None,
        "rollback_hold_count": reasons.get("rollback_accept_rate_breached", 0),
        "modes": dict(sorted(modes.items())),
        "reasons": dict(sorted(reasons.items())),
    }


def _bounded_capabilities(
    capabilities: tuple[ChatModelCapability, ...],
    *,
    rows: Mapping[str, Mapping[str, object]],
    min_samples: int,
    max_score_delta: int,
) -> tuple[ChatModelCapability, ...]:
    calibrated: list[ChatModelCapability] = []
    for capability in capabilities:
        row = rows.get(capability.route_mode, {})
        raw_delta = _int_value(row.get("score_delta"))
        delta = (
            max(-max_score_delta, min(max_score_delta, raw_delta))
            if _sample_count(row) >= min_samples
            else 0
        )
        calibrated.append(
            replace(
                capability,
                reliability_score=_clamp_score(capability.reliability_score + delta),
                task_scores={
                    task: _clamp_score(task_score + delta)
                    for task, task_score in capability.task_scores.items()
                },
            )
        )
    return tuple(calibrated)


def _applied_rollout_stats(
    outcomes: Sequence[Mapping[str, object]],
) -> tuple[int, float | None]:
    applied = [
        outcome
        for outcome in outcomes
        if outcome.get("chat_calibrated_routing_schema_version")
        == CHAT_CALIBRATED_ROUTING_ROLLOUT_VERSION
        and outcome.get("chat_calibrated_routing_applied") is True
    ]
    if not applied:
        return 0, None
    accepted = sum(
        1
        for outcome in applied
        if outcome.get("chat_outcome_quality_action") == "accept"
    )
    return len(applied), round(accepted / len(applied), 3)


def _sample_count(row: Mapping[str, object] | None) -> int:
    return _int_value(row.get("sample_count")) if row else 0


def _rollout_bucket(rollout_key: str) -> int:
    digest = hashlib.sha256(
        f"{CHAT_CALIBRATED_ROUTING_ROLLOUT_VERSION}:{rollout_key}".encode()
    ).digest()
    return int.from_bytes(digest[:4], "big") % 100 + 1


def _bounded_int_env(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> tuple[int, bool]:
    raw = os.getenv(name)
    if raw is None:
        return default, True
    try:
        value = int(raw)
    except ValueError:
        return default, False
    return (value, True) if minimum <= value <= maximum else (default, False)


def _bounded_float_env(
    name: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> tuple[float, bool]:
    raw = os.getenv(name)
    if raw is None:
        return default, True
    try:
        value = float(raw)
    except ValueError:
        return default, False
    return (value, True) if minimum <= value <= maximum else (default, False)


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _clamp_score(value: int | float) -> int:
    return max(0, min(100, round(value)))
