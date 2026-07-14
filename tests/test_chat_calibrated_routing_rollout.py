from __future__ import annotations

from brain.routing.calibrated_rollout import (
    CHAT_CALIBRATED_ROUTING_ROLLOUT_VERSION,
    ChatCalibratedRoutingPolicy,
    calibrated_routing_observation_enabled,
    calibrated_routing_rollout_metrics,
    plan_calibrated_routing,
)
from brain.routing.model_capability_registry import select_chat_model_for_task

ANALYSIS_PROMPT = "Summarize the AT-0 architecture tradeoffs."


def test_rollout_is_default_off_and_keeps_static_route() -> None:
    decision = plan_calibrated_routing(
        prompt=ANALYSIS_PROMPT,
        outcomes=_route_changing_outcomes(),
    )

    assert decision.mode == "off"
    assert decision.applied is False
    assert decision.reason == "rollout_disabled"
    assert decision.baseline_route_mode == "claude"
    assert decision.candidate_route_mode == "claude"
    assert select_chat_model_for_task(
        decision.task_class,
        capabilities=decision.routing_capabilities,
    ).route_mode == ("claude")


def test_shadow_reports_candidate_without_changing_route() -> None:
    policy = ChatCalibratedRoutingPolicy(mode="shadow")
    decision = plan_calibrated_routing(
        prompt=ANALYSIS_PROMPT,
        outcomes=_route_changing_outcomes(),
        rollout_key="thread-shadow",
        policy=policy,
    )

    assert decision.applied is False
    assert decision.reason == "shadow_candidate_ready"
    assert decision.baseline_route_mode == "claude"
    assert decision.candidate_route_mode == "gemini"
    assert decision.baseline_samples == 10
    assert decision.candidate_samples == 10
    assert select_chat_model_for_task(
        decision.task_class,
        capabilities=decision.routing_capabilities,
    ).route_mode == ("claude")


def test_active_rollout_applies_bounded_candidate_at_full_canary() -> None:
    policy = ChatCalibratedRoutingPolicy(mode="active", rollout_percent=100)
    decision = plan_calibrated_routing(
        prompt=ANALYSIS_PROMPT,
        outcomes=_route_changing_outcomes(),
        rollout_key="thread-active",
        policy=policy,
    )

    assert decision.applied is True
    assert decision.reason == "calibrated_route_selected"
    assert decision.rollout_bucket is not None
    assert decision.candidate_route_mode == "gemini"
    selected = select_chat_model_for_task(
        decision.task_class,
        capabilities=decision.routing_capabilities,
    )
    by_route = {
        capability.route_mode: capability
        for capability in decision.routing_capabilities
    }
    assert selected.route_mode == "gemini"
    assert by_route["claude"].task_scores["analysis"] == 95
    assert by_route["gemini"].task_scores["analysis"] == 95
    assert "thread-active" not in str(decision.metadata())


def test_active_rollout_holds_when_route_samples_are_insufficient() -> None:
    policy = ChatCalibratedRoutingPolicy(mode="active", rollout_percent=100)
    decision = plan_calibrated_routing(
        prompt=ANALYSIS_PROMPT,
        outcomes=_route_changing_outcomes(samples=3),
        rollout_key="thread-active",
        policy=policy,
    )

    assert decision.applied is False
    assert decision.reason == "insufficient_route_samples"
    assert decision.baseline_samples == 3


def test_active_rollout_auto_holds_after_acceptance_floor_breach() -> None:
    policy = ChatCalibratedRoutingPolicy(mode="active", rollout_percent=100)
    outcomes = _route_changing_outcomes(applied_bad_route=True)
    decision = plan_calibrated_routing(
        prompt=ANALYSIS_PROMPT,
        outcomes=outcomes,
        rollout_key="thread-active",
        policy=policy,
    )

    assert decision.applied is False
    assert decision.reason == "rollback_accept_rate_breached"
    assert decision.rollback_samples == 10
    assert decision.rollback_accept_rate == 0.0


def test_rollback_ignores_unversioned_applied_metadata() -> None:
    policy = ChatCalibratedRoutingPolicy(mode="active", rollout_percent=100)
    outcomes = _route_changing_outcomes(applied_bad_route=True)
    for outcome in outcomes:
        outcome.pop("chat_calibrated_routing_schema_version", None)

    decision = plan_calibrated_routing(
        prompt=ANALYSIS_PROMPT,
        outcomes=outcomes,
        rollout_key="thread-active",
        policy=policy,
    )

    assert decision.rollback_samples == 0
    assert decision.applied is True


def test_invalid_environment_policy_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("ALPHA_CHAT_CALIBRATED_ROUTING_MODE", "active")
    monkeypatch.setenv("ALPHA_CHAT_CALIBRATED_ROUTING_PERCENT", "101")

    policy = ChatCalibratedRoutingPolicy.from_env()
    decision = plan_calibrated_routing(
        prompt=ANALYSIS_PROMPT,
        outcomes=_route_changing_outcomes(),
        rollout_key="thread-active",
        policy=policy,
    )

    assert policy.configuration_valid is False
    assert policy.mode == "off"
    assert calibrated_routing_observation_enabled(policy) is False
    assert decision.reason == "invalid_policy_fail_closed"
    assert decision.applied is False


def test_rollout_metrics_are_compact_and_metadata_only() -> None:
    outcomes = [
        {
            "chat_calibrated_routing_schema_version": (
                CHAT_CALIBRATED_ROUTING_ROLLOUT_VERSION
            ),
            "chat_calibrated_routing_mode": "shadow",
            "chat_calibrated_routing_applied": False,
            "chat_calibrated_routing_reason": "shadow_candidate_ready",
        },
        {
            "chat_calibrated_routing_schema_version": (
                CHAT_CALIBRATED_ROUTING_ROLLOUT_VERSION
            ),
            "chat_calibrated_routing_mode": "active",
            "chat_calibrated_routing_applied": True,
            "chat_calibrated_routing_reason": "calibrated_route_selected",
        },
    ]

    metrics = calibrated_routing_rollout_metrics(outcomes)

    assert metrics["observed_outcome_count"] == 2
    assert metrics["applied_outcome_count"] == 1
    assert metrics["apply_rate"] == 0.5
    assert metrics["modes"] == {"active": 1, "shadow": 1}
    assert "content" not in metrics


def _route_changing_outcomes(
    *,
    samples: int = 10,
    applied_bad_route: bool = False,
) -> list[dict[str, object]]:
    outcomes: list[dict[str, object]] = []
    for _ in range(samples):
        outcomes.append(
            {
                "chat_outcome_route_mode": "claude",
                "chat_outcome_quality_action": "replace_with_safe_fallback",
                "chat_outcome_escalation_rung": "operator_review",
                "chat_outcome_escalation_required": True,
                "chat_outcome_fallback_used": True,
                "chat_outcome_issue_count": 2,
                "chat_calibrated_routing_applied": applied_bad_route,
                "chat_calibrated_routing_schema_version": (
                    CHAT_CALIBRATED_ROUTING_ROLLOUT_VERSION
                    if applied_bad_route
                    else None
                ),
            }
        )
        outcomes.append(
            {
                "chat_outcome_route_mode": "gemini",
                "chat_outcome_quality_action": "accept",
                "chat_outcome_escalation_rung": "none",
                "chat_outcome_escalation_required": False,
                "chat_outcome_fallback_used": False,
                "chat_outcome_issue_count": 0,
            }
        )
    return outcomes
