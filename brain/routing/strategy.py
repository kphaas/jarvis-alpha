from dataclasses import dataclass
from typing import Literal

from brain.routing.complexity import score
from brain.routing.model_capability_registry import (
    DEFAULT_CHAT_MODEL_CAPABILITIES,
    ChatModelCapability,
    get_chat_model_capability,
    select_chat_model_for_task,
    task_class_for_complexity,
)

ChatStrategyName = Literal[
    "fast_local",
    "grounded_local",
    "direct_cloud",
    "hybrid_cloud_final",
    "council_light",
    "deep_verify",
]


@dataclass(frozen=True)
class ChatStrategyPlan:
    strategy: ChatStrategyName
    route_mode: str
    model_path: tuple[str, ...]
    reason: str
    model_capability: ChatModelCapability | None = None

    def metadata(self) -> dict[str, object]:
        metadata = {
            "chat_strategy": self.strategy,
            "chat_route_mode": self.route_mode,
            "chat_model_path": list(self.model_path),
            "chat_strategy_reason": self.reason,
        }
        if self.model_capability:
            metadata.update(self.model_capability.metadata())
        return metadata


def select_chat_strategy(
    *,
    prompt: str,
    requested_model: str = "auto",
    internet_mode: str = "none",
    council_models: list[str] | tuple[str, ...] = (),
    capabilities: tuple[ChatModelCapability, ...] = DEFAULT_CHAT_MODEL_CAPABILITIES,
) -> ChatStrategyPlan:
    model = (requested_model or "auto").lower()
    internet = (internet_mode or "none").lower()

    if model == "council" or len(council_models) >= 2:
        models = tuple(council_models) if council_models else ("claude", "gemini")
        return ChatStrategyPlan(
            strategy="council_light",
            route_mode="council",
            model_path=models,
            reason="council_requested",
        )

    if internet == "deep_research":
        capability = (
            select_chat_model_for_task("deep", capabilities=capabilities)
            if model == "auto"
            else get_chat_model_capability(model, capabilities=capabilities)
        )
        route_mode = capability.route_mode if capability else model
        return ChatStrategyPlan(
            strategy="deep_verify",
            route_mode=route_mode,
            model_path=("beacon/deep_research", route_mode),
            reason="deep_research_requested",
            model_capability=capability,
        )

    if internet == "web_search":
        capability = (
            select_chat_model_for_task("grounded", capabilities=capabilities)
            if model == "auto"
            else get_chat_model_capability(model, capabilities=capabilities)
        )
        route_mode = capability.route_mode if capability else model
        return ChatStrategyPlan(
            strategy="grounded_local",
            route_mode=route_mode,
            model_path=("beacon/web_search", route_mode),
            reason="web_search_requested",
            model_capability=capability,
        )

    if model == "auto":
        complexity = score(prompt)
        capability = select_chat_model_for_task(
            task_class_for_complexity(complexity),
            capabilities=capabilities,
        )
        route_mode = capability.route_mode
        return ChatStrategyPlan(
            strategy=_strategy_for_route_mode(route_mode, auto=True),
            route_mode=route_mode,
            model_path=(route_mode,),
            reason=f"auto_complexity_{complexity}",
            model_capability=capability,
        )

    capability = get_chat_model_capability(model, capabilities=capabilities)
    return ChatStrategyPlan(
        strategy=_strategy_for_route_mode(model, auto=False),
        route_mode=model,
        model_path=(model,),
        reason="explicit_model_requested",
        model_capability=capability,
    )


def _auto_route_mode(prompt: str) -> str:
    complexity = score(prompt)
    capability = select_chat_model_for_task(task_class_for_complexity(complexity))
    return capability.route_mode


def _strategy_for_route_mode(route_mode: str, *, auto: bool) -> ChatStrategyName:
    if route_mode == "local":
        return "fast_local"
    if route_mode == "perplexity":
        return "grounded_local"
    if route_mode in {"claude", "gemini"}:
        return "hybrid_cloud_final" if auto else "direct_cloud"
    return "fast_local"
