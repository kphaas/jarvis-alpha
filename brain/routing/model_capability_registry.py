"""Versioned model capability data for chat routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from brain.core.models import CLAUDE_SMART, GEMINI_FAST, LOCAL_CHAT, PERPLEXITY_FAST

ChatTaskClass = Literal["fast", "grounded", "analysis", "deep"]
ModelDeployment = Literal["local", "brokered", "cloud"]
PrivacyTier = Literal["local", "brokered", "external"]

CHAT_MODEL_CAPABILITY_REGISTRY_VERSION = "chat_model_capability_registry.v2"


@dataclass(frozen=True)
class ChatModelCapability:
    route_mode: str
    provider: str
    model_id: str
    deployment: ModelDeployment
    cost_tier: int
    latency_tier: int
    context_window_tokens: int
    supports_tools: bool
    supports_web_search: bool
    supports_deep_research: bool
    privacy_tier: PrivacyTier
    reliability_score: int
    task_scores: dict[ChatTaskClass, int]

    def metadata(self) -> dict[str, object]:
        return {
            "chat_model_registry_version": CHAT_MODEL_CAPABILITY_REGISTRY_VERSION,
            "chat_model_provider": self.provider,
            "chat_model_id": self.model_id,
            "chat_model_deployment": self.deployment,
            "chat_model_cost_tier": self.cost_tier,
            "chat_model_latency_tier": self.latency_tier,
            "chat_model_context_window_tokens": self.context_window_tokens,
            "chat_model_supports_tools": self.supports_tools,
            "chat_model_supports_web_search": self.supports_web_search,
            "chat_model_supports_deep_research": self.supports_deep_research,
            "chat_model_privacy_tier": self.privacy_tier,
            "chat_model_reliability_score": self.reliability_score,
        }

    def score_for(self, task: ChatTaskClass) -> tuple[int, int, int, int, int, str]:
        return (
            self.task_scores.get(task, 0),
            self.reliability_score,
            -self.cost_tier,
            -self.latency_tier,
            self.context_window_tokens,
            self.route_mode,
        )


DEFAULT_CHAT_MODEL_CAPABILITIES: tuple[ChatModelCapability, ...] = (
    ChatModelCapability(
        route_mode="local",
        provider="ollama",
        model_id=LOCAL_CHAT,
        deployment="local",
        cost_tier=0,
        latency_tier=1,
        context_window_tokens=32768,
        supports_tools=False,
        supports_web_search=False,
        supports_deep_research=False,
        privacy_tier="local",
        reliability_score=78,
        task_scores={"fast": 100, "grounded": 45, "analysis": 55, "deep": 40},
    ),
    ChatModelCapability(
        route_mode="perplexity",
        provider="perplexity",
        model_id=PERPLEXITY_FAST,
        deployment="brokered",
        cost_tier=2,
        latency_tier=3,
        context_window_tokens=128000,
        supports_tools=False,
        supports_web_search=True,
        supports_deep_research=False,
        privacy_tier="external",
        reliability_score=82,
        task_scores={"fast": 40, "grounded": 100, "analysis": 62, "deep": 68},
    ),
    ChatModelCapability(
        route_mode="claude",
        provider="anthropic",
        model_id=CLAUDE_SMART,
        deployment="cloud",
        cost_tier=4,
        latency_tier=4,
        context_window_tokens=200000,
        supports_tools=True,
        supports_web_search=False,
        supports_deep_research=False,
        privacy_tier="external",
        reliability_score=92,
        task_scores={"fast": 35, "grounded": 68, "analysis": 100, "deep": 86},
    ),
    ChatModelCapability(
        route_mode="gemini",
        provider="google",
        model_id=GEMINI_FAST,
        deployment="cloud",
        cost_tier=3,
        latency_tier=4,
        context_window_tokens=1_000_000,
        supports_tools=True,
        supports_web_search=False,
        supports_deep_research=True,
        privacy_tier="external",
        reliability_score=88,
        task_scores={"fast": 32, "grounded": 70, "analysis": 90, "deep": 100},
    ),
)


def task_class_for_complexity(complexity: int | str) -> ChatTaskClass:
    if complexity in (1, 2) or complexity in {"code", "scrape"}:
        return "fast"
    if complexity == 3:
        return "grounded"
    if complexity == 4:
        return "analysis"
    return "deep"


def select_chat_model_for_task(
    task: ChatTaskClass,
    *,
    capabilities: tuple[ChatModelCapability, ...] = DEFAULT_CHAT_MODEL_CAPABILITIES,
) -> ChatModelCapability:
    return max(capabilities, key=lambda capability: capability.score_for(task))


def get_chat_model_capability(
    route_mode: str,
    *,
    capabilities: tuple[ChatModelCapability, ...] = DEFAULT_CHAT_MODEL_CAPABILITIES,
) -> ChatModelCapability | None:
    normalized = (route_mode or "").lower()
    return next(
        (
            capability
            for capability in capabilities
            if capability.route_mode == normalized
        ),
        None,
    )
