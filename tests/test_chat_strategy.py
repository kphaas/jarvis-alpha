from brain.routing.model_capability_registry import (
    CHAT_MODEL_CAPABILITY_REGISTRY_VERSION,
    ChatModelCapability,
)
from brain.routing.strategy import select_chat_strategy


def test_auto_routes_short_prompts_to_fast_local() -> None:
    plan = select_chat_strategy(prompt="what is next?", requested_model="auto")

    assert plan.strategy == "fast_local"
    assert plan.route_mode == "local"
    assert plan.model_path == ("local",)
    assert plan.reason == "auto_complexity_1"


def test_auto_routes_current_public_questions_to_grounded_path() -> None:
    plan = select_chat_strategy(
        prompt="Find the latest OpenAI API docs.",
        requested_model="auto",
    )

    assert plan.strategy == "grounded_local"
    assert plan.route_mode == "perplexity"
    assert plan.model_path == ("perplexity",)


def test_auto_routes_analysis_to_cloud_finalizer_strategy() -> None:
    plan = select_chat_strategy(
        prompt="Summarize the AT-0 architecture tradeoffs.",
        requested_model="auto",
    )

    assert plan.strategy == "hybrid_cloud_final"
    assert plan.route_mode == "claude"
    assert plan.model_path == ("claude",)


def test_explicit_cloud_model_is_direct_cloud_strategy() -> None:
    plan = select_chat_strategy(
        prompt="Explain this migration plan.",
        requested_model="gemini",
    )

    assert plan.strategy == "direct_cloud"
    assert plan.route_mode == "gemini"
    assert plan.model_path == ("gemini",)


def test_deep_research_marks_strategy_without_overriding_explicit_model() -> None:
    plan = select_chat_strategy(
        prompt="Research current model pricing.",
        requested_model="local",
        internet_mode="deep_research",
    )

    assert plan.strategy == "deep_verify"
    assert plan.route_mode == "local"
    assert plan.model_path == ("beacon/deep_research", "local")


def test_council_models_map_to_council_light_strategy() -> None:
    plan = select_chat_strategy(
        prompt="Review the architecture.",
        requested_model="auto",
        council_models=["claude", "gemini"],
    )

    assert plan.strategy == "council_light"
    assert plan.route_mode == "council"
    assert plan.model_path == ("claude", "gemini")


def test_chat_strategy_sse_metadata_is_stable_for_helm() -> None:
    plan = select_chat_strategy(prompt="what is next?", requested_model="auto")

    payload = plan.metadata()
    payload["thread_id"] = "thread-1"
    payload["done"] = False

    assert payload == {
        "chat_strategy": "fast_local",
        "chat_route_mode": "local",
        "chat_model_path": ["local"],
        "chat_strategy_reason": "auto_complexity_1",
        "chat_model_registry_version": CHAT_MODEL_CAPABILITY_REGISTRY_VERSION,
        "chat_model_provider": "ollama",
        "chat_model_id": "llama3.1:8b",
        "chat_model_deployment": "local",
        "chat_model_cost_tier": 0,
        "chat_model_latency_tier": 1,
        "chat_model_context_window_tokens": 32768,
        "chat_model_supports_tools": False,
        "chat_model_supports_web_search": False,
        "chat_model_supports_deep_research": False,
        "chat_model_privacy_tier": "local",
        "chat_model_reliability_score": 78,
        "thread_id": "thread-1",
        "done": False,
    }


def test_auto_strategy_uses_capability_registry_scores() -> None:
    custom_capabilities = (
        ChatModelCapability(
            route_mode="local",
            provider="local-test",
            model_id="local-test-v1",
            deployment="local",
            cost_tier=0,
            latency_tier=1,
            context_window_tokens=4096,
            supports_tools=False,
            supports_web_search=False,
            supports_deep_research=False,
            privacy_tier="local",
            reliability_score=80,
            task_scores={"fast": 100, "grounded": 100, "analysis": 100, "deep": 100},
        ),
        ChatModelCapability(
            route_mode="claude",
            provider="cloud-test",
            model_id="cloud-test-v1",
            deployment="cloud",
            cost_tier=5,
            latency_tier=5,
            context_window_tokens=200000,
            supports_tools=True,
            supports_web_search=False,
            supports_deep_research=False,
            privacy_tier="external",
            reliability_score=99,
            task_scores={"fast": 1, "grounded": 1, "analysis": 1, "deep": 1},
        ),
    )

    plan = select_chat_strategy(
        prompt="Summarize the AT-0 architecture tradeoffs.",
        requested_model="auto",
        capabilities=custom_capabilities,
    )

    assert plan.route_mode == "local"
    assert plan.metadata()["chat_model_provider"] == "local-test"
