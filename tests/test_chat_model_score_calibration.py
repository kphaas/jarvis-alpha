from __future__ import annotations

from brain.routing.model_score_calibration import (
    CHAT_MODEL_SCORE_CALIBRATION_VERSION,
    calibrated_chat_model_capabilities,
    chat_model_score_calibration_payload,
)


def test_model_score_calibration_uses_outcome_rates_without_raw_content() -> None:
    payload = chat_model_score_calibration_payload(
        [
            _outcome("local", action="accept"),
            _outcome("local", action="accept"),
            _outcome("local", action="replace_with_safe_fallback", fallback=True),
            _outcome("perplexity", action="require_beacon", rung="beacon"),
            _outcome("perplexity", action="require_beacon", rung="beacon"),
            _outcome("perplexity", action="require_beacon", rung="beacon"),
        ]
    )

    rows = {row["route_mode"]: row for row in payload["calibrated_models"]}

    assert payload["schema_version"] == CHAT_MODEL_SCORE_CALIBRATION_VERSION
    assert payload["evaluated_outcome_count"] == 6
    assert rows["local"]["confidence"] == "low_sample"
    assert rows["local"]["sample_count"] == 3
    assert rows["local"]["score_delta"] < 0
    assert rows["perplexity"]["escalation_rate"] == 1.0
    assert rows["perplexity"]["score_delta"] < rows["local"]["score_delta"]
    assert "content" not in str(payload).lower()


def test_model_score_calibration_keeps_scores_static_until_enough_samples() -> None:
    payload = chat_model_score_calibration_payload([_outcome("local", action="accept")])
    local = next(
        row for row in payload["calibrated_models"] if row["route_mode"] == "local"
    )

    assert local["confidence"] == "insufficient_data"
    assert local["score_delta"] == 0
    assert local["baseline_reliability_score"] == local["calibrated_reliability_score"]


def test_calibrated_capabilities_can_be_supplied_to_strategy_later() -> None:
    calibrated = calibrated_chat_model_capabilities(
        [
            _outcome("claude", action="accept"),
            _outcome("claude", action="accept"),
            _outcome("claude", action="accept"),
            _outcome("gemini", action="require_beacon", rung="operator_review"),
            _outcome("gemini", action="replace_with_safe_fallback", fallback=True),
            _outcome("gemini", action="require_beacon", rung="operator_review"),
        ]
    )
    by_route = {capability.route_mode: capability for capability in calibrated}

    assert by_route["claude"].reliability_score > 92
    assert by_route["gemini"].reliability_score < 88
    assert by_route["claude"].task_scores["analysis"] == 100
    assert by_route["gemini"].task_scores["deep"] < 100


def _outcome(
    route_mode: str,
    *,
    action: str,
    rung: str = "none",
    fallback: bool = False,
    issue_count: int = 0,
) -> dict[str, object]:
    return {
        "chat_outcome_schema_version": "chat_outcome.v1",
        "chat_outcome_route_mode": route_mode,
        "chat_outcome_quality_action": action,
        "chat_outcome_escalation_rung": rung,
        "chat_outcome_escalation_required": rung != "none",
        "chat_outcome_fallback_used": fallback,
        "chat_outcome_issue_count": issue_count,
    }
