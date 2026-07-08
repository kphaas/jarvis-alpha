from dataclasses import dataclass
from typing import Literal

from brain.routing.complexity import score

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

    def metadata(self) -> dict[str, object]:
        return {
            "chat_strategy": self.strategy,
            "chat_route_mode": self.route_mode,
            "chat_model_path": list(self.model_path),
            "chat_strategy_reason": self.reason,
        }


def select_chat_strategy(
    *,
    prompt: str,
    requested_model: str = "auto",
    internet_mode: str = "none",
    council_models: list[str] | tuple[str, ...] = (),
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
        route_mode = _auto_route_mode(prompt) if model == "auto" else model
        return ChatStrategyPlan(
            strategy="deep_verify",
            route_mode=route_mode,
            model_path=("beacon/deep_research", route_mode),
            reason="deep_research_requested",
        )

    if internet == "web_search":
        route_mode = _auto_route_mode(prompt) if model == "auto" else model
        return ChatStrategyPlan(
            strategy="grounded_local",
            route_mode=route_mode,
            model_path=("beacon/web_search", route_mode),
            reason="web_search_requested",
        )

    if model == "auto":
        route_mode = _auto_route_mode(prompt)
        return ChatStrategyPlan(
            strategy=_strategy_for_route_mode(route_mode, auto=True),
            route_mode=route_mode,
            model_path=(route_mode,),
            reason=f"auto_complexity_{score(prompt)}",
        )

    return ChatStrategyPlan(
        strategy=_strategy_for_route_mode(model, auto=False),
        route_mode=model,
        model_path=(model,),
        reason="explicit_model_requested",
    )


def _auto_route_mode(prompt: str) -> str:
    complexity = score(prompt)
    if complexity in (1, 2) or complexity == "code" or complexity == "scrape":
        return "local"
    if complexity == 3:
        return "perplexity"
    if complexity == 4:
        return "claude"
    return "gemini"


def _strategy_for_route_mode(route_mode: str, *, auto: bool) -> ChatStrategyName:
    if route_mode == "local":
        return "fast_local"
    if route_mode == "perplexity":
        return "grounded_local"
    if route_mode in {"claude", "gemini"}:
        return "hybrid_cloud_final" if auto else "direct_cloud"
    return "fast_local"
