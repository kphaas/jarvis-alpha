from brain.routing.model_capability_registry import (
    CHAT_MODEL_CAPABILITY_REGISTRY_VERSION,
    DEFAULT_CHAT_MODEL_CAPABILITIES,
    get_chat_model_capability,
    select_chat_model_for_task,
    task_class_for_complexity,
)
from brain.routing.model_score_calibration import calibrated_chat_model_capabilities


def test_default_chat_model_registry_has_required_routing_tags() -> None:
    local = get_chat_model_capability("local")

    assert local is not None
    assert local.metadata() == {
        "chat_model_registry_version": CHAT_MODEL_CAPABILITY_REGISTRY_VERSION,
        "chat_model_provider": "ollama",
        "chat_model_deployment": "local",
        "chat_model_cost_tier": 0,
        "chat_model_latency_tier": 1,
        "chat_model_context_window_tokens": 32768,
        "chat_model_supports_tools": False,
        "chat_model_supports_web_search": False,
        "chat_model_supports_deep_research": False,
        "chat_model_privacy_tier": "local",
        "chat_model_reliability_score": 78,
    }


def test_registry_selects_expected_default_task_routes() -> None:
    assert select_chat_model_for_task("fast").route_mode == "local"
    assert select_chat_model_for_task("grounded").route_mode == "perplexity"
    assert select_chat_model_for_task("analysis").route_mode == "claude"
    assert select_chat_model_for_task("deep").route_mode == "gemini"


def test_registry_contract_covers_all_default_route_modes() -> None:
    route_modes = {
        capability.route_mode for capability in DEFAULT_CHAT_MODEL_CAPABILITIES
    }

    assert route_modes == {"local", "perplexity", "claude", "gemini"}
    assert task_class_for_complexity(1) == "fast"
    assert task_class_for_complexity(3) == "grounded"
    assert task_class_for_complexity(4) == "analysis"
    assert task_class_for_complexity(5) == "deep"


def test_registry_can_accept_outcome_calibrated_capabilities() -> None:
    calibrated = calibrated_chat_model_capabilities(
        [
            {
                "chat_outcome_route_mode": "claude",
                "chat_outcome_quality_action": "accept",
                "chat_outcome_escalation_rung": "none",
            },
            {
                "chat_outcome_route_mode": "claude",
                "chat_outcome_quality_action": "accept",
                "chat_outcome_escalation_rung": "none",
            },
            {
                "chat_outcome_route_mode": "claude",
                "chat_outcome_quality_action": "accept",
                "chat_outcome_escalation_rung": "none",
            },
        ]
    )

    assert select_chat_model_for_task(
        "analysis", capabilities=calibrated
    ).route_mode == ("claude")
