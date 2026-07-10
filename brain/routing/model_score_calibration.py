"""Outcome-calibrated score overlays for chat model routing."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace

from brain.routing.model_capability_registry import (
    CHAT_MODEL_CAPABILITY_REGISTRY_VERSION,
    DEFAULT_CHAT_MODEL_CAPABILITIES,
    ChatModelCapability,
)

CHAT_MODEL_SCORE_CALIBRATION_VERSION = "chat_model_score_calibration.v1"
MIN_CALIBRATION_SAMPLES = 3


def chat_model_score_calibration_payload(
    outcomes: Sequence[Mapping[str, object]],
    *,
    capabilities: tuple[ChatModelCapability, ...] = DEFAULT_CHAT_MODEL_CAPABILITIES,
) -> dict[str, object]:
    summaries = _route_summaries(outcomes)
    rows = [
        _calibrated_row(capability, summaries.get(capability.route_mode, {}))
        for capability in capabilities
    ]
    return {
        "schema_version": CHAT_MODEL_SCORE_CALIBRATION_VERSION,
        "registry_version": CHAT_MODEL_CAPABILITY_REGISTRY_VERSION,
        "evaluated_outcome_count": len(outcomes),
        "min_samples": MIN_CALIBRATION_SAMPLES,
        "calibrated_models": rows,
    }


def calibrated_chat_model_capabilities(
    outcomes: Sequence[Mapping[str, object]],
    *,
    capabilities: tuple[ChatModelCapability, ...] = DEFAULT_CHAT_MODEL_CAPABILITIES,
) -> tuple[ChatModelCapability, ...]:
    payload = chat_model_score_calibration_payload(outcomes, capabilities=capabilities)
    deltas = {
        str(row["route_mode"]): int(row["score_delta"])
        for row in payload["calibrated_models"]
        if isinstance(row, Mapping)
    }
    return tuple(
        replace(
            capability,
            reliability_score=_clamp_score(
                capability.reliability_score + deltas.get(capability.route_mode, 0)
            ),
            task_scores={
                task: _clamp_score(score + deltas.get(capability.route_mode, 0))
                for task, score in capability.task_scores.items()
            },
        )
        for capability in capabilities
    )


def _route_summaries(
    outcomes: Sequence[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for outcome in outcomes:
        route_mode = str(outcome.get("chat_outcome_route_mode") or "").lower()
        if route_mode:
            grouped[route_mode].append(outcome)

    summaries: dict[str, dict[str, object]] = {}
    for route_mode, rows in grouped.items():
        actions = Counter(
            str(row.get("chat_outcome_quality_action") or "unknown") for row in rows
        )
        escalated = sum(1 for row in rows if _outcome_escalated(row))
        fallback = sum(1 for row in rows if bool(row.get("chat_outcome_fallback_used")))
        issue_count = sum(
            _int_value(row.get("chat_outcome_issue_count")) for row in rows
        )
        count = len(rows)
        summaries[route_mode] = {
            "sample_count": count,
            "accept_count": actions.get("accept", 0),
            "escalated_count": escalated,
            "fallback_count": fallback,
            "issue_count": issue_count,
            "quality_actions": dict(sorted(actions.items())),
            "accept_rate": round(actions.get("accept", 0) / count, 3),
            "escalation_rate": round(escalated / count, 3),
            "fallback_rate": round(fallback / count, 3),
            "issue_rate": round(issue_count / count, 3),
        }
    return summaries


def _calibrated_row(
    capability: ChatModelCapability,
    summary: Mapping[str, object],
) -> dict[str, object]:
    sample_count = _int_value(summary.get("sample_count"))
    baseline = capability.reliability_score
    if sample_count < MIN_CALIBRATION_SAMPLES:
        delta = 0
        confidence = "insufficient_data"
        reason = "insufficient_outcome_samples"
    else:
        delta = _score_delta(summary)
        confidence = "sampled" if sample_count >= 10 else "low_sample"
        reason = "outcome_calibrated"
    calibrated = _clamp_score(baseline + delta)
    return {
        "route_mode": capability.route_mode,
        "provider": capability.provider,
        "baseline_reliability_score": baseline,
        "calibrated_reliability_score": calibrated,
        "score_delta": delta,
        "sample_count": sample_count,
        "confidence": confidence,
        "reason": reason,
        "accept_rate": summary.get("accept_rate"),
        "escalation_rate": summary.get("escalation_rate"),
        "fallback_rate": summary.get("fallback_rate"),
        "issue_rate": summary.get("issue_rate"),
        "quality_actions": summary.get("quality_actions", {}),
    }


def _score_delta(summary: Mapping[str, object]) -> int:
    accept_rate = _float_value(summary.get("accept_rate"))
    escalation_rate = _float_value(summary.get("escalation_rate"))
    fallback_rate = _float_value(summary.get("fallback_rate"))
    issue_rate = min(_float_value(summary.get("issue_rate")), 5.0)
    return round(
        ((accept_rate - 0.75) * 20)
        - (escalation_rate * 15)
        - (fallback_rate * 10)
        - (issue_rate * 2)
    )


def _outcome_escalated(outcome: Mapping[str, object]) -> bool:
    return bool(outcome.get("chat_outcome_escalation_required")) or (
        str(outcome.get("chat_outcome_escalation_rung") or "none") != "none"
    )


def _int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float_value(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _clamp_score(value: int | float) -> int:
    return max(0, min(100, round(value)))
