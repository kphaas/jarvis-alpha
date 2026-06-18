"""Conservative Beacon suggestion policy for chat requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from brain.services.internet_scout.models import Sensitivity

WebSuggestionMode = Literal["web_search", "deep_research"]
WebSuggestionConfidence = Literal["medium", "high"]


@dataclass(frozen=True)
class WebSuggestion:
    mode: WebSuggestionMode
    reason: str
    confidence: WebSuggestionConfidence
    query: str
    requires_confirmation: bool = True

    def to_metadata(self) -> dict[str, object]:
        return {
            "web_suggestion_mode": self.mode,
            "web_suggestion_reason": self.reason,
            "web_suggestion_confidence": self.confidence,
            "web_suggestion_query": self.query,
            "web_suggestion_requires_confirmation": self.requires_confirmation,
            "web_suggestion_source": "alpha_smart_web_suggestion",
        }


_CURRENT_TERMS = (
    "today",
    "tomorrow",
    "tonight",
    "yesterday",
    "latest",
    "current",
    "recent",
    "right now",
    "this week",
    "this month",
    "new release",
    "release notes",
    "changelog",
    "version",
    "news",
    "price",
    "market",
    "weather",
    "schedule",
    "score",
    "status",
    "ceo",
)

_SPORTS_EVENT_TERMS = (
    "fifa",
    "world cup",
    "usmnt",
    "uswnt",
    "soccer",
    "football",
    "match",
    "fixture",
    "kickoff",
    "kick off",
    "opponent",
    "game",
    "score",
    "standings",
    "play",
    "playing",
)

_TIME_QUESTION_TERMS = (
    "when",
    "what time",
    "which day",
    "schedule",
    "fixture",
    "today",
    "tomorrow",
    "tonight",
    "this week",
    "next",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

_SOURCE_TERMS = (
    "cite",
    "citation",
    "source",
    "sources",
    "link",
    "url",
    "reference",
    "official",
    "documentation",
    "docs",
    "api reference",
)

_SEARCH_TERMS = (
    "search",
    "look up",
    "find online",
    "on the web",
    "internet",
    "web",
)

_PRIVATE_TERMS = (
    "my girlfriend",
    "my wife",
    "my kid",
    "my child",
    "my family",
    "my bank",
    "my account",
    "my password",
    "my pin",
    "my ssn",
    "my social security",
)


def suggest_web_for_chat(
    *,
    query: str,
    internet_mode: str,
    sensitivity: Sensitivity,
) -> WebSuggestion | None:
    """Return a one-click Beacon suggestion without running internet egress."""
    clean_query = " ".join(query.split())
    if not clean_query or internet_mode != "none" or sensitivity == "minor":
        return None

    lowered = clean_query.lower()
    explicit_search = any(term in lowered for term in _SEARCH_TERMS)
    source_intent = any(term in lowered for term in _SOURCE_TERMS)
    current_intent = any(term in lowered for term in _CURRENT_TERMS)
    sports_schedule_intent = any(
        term in lowered for term in _SPORTS_EVENT_TERMS
    ) and any(term in lowered for term in _TIME_QUESTION_TERMS)
    private_intent = any(term in lowered for term in _PRIVATE_TERMS)

    if private_intent and not (explicit_search or source_intent):
        return None

    if source_intent and (
        "official" in lowered
        or "api reference" in lowered
        or "documentation" in lowered
        or "docs" in lowered
    ):
        return WebSuggestion(
            mode="deep_research",
            reason="official_source_requested",
            confidence="high",
            query=clean_query,
        )

    if explicit_search and source_intent:
        return WebSuggestion(
            mode="deep_research",
            reason="cited_research_requested",
            confidence="high",
            query=clean_query,
        )

    if source_intent:
        return WebSuggestion(
            mode="web_search",
            reason="source_requested",
            confidence="medium",
            query=clean_query,
        )

    if sports_schedule_intent:
        return WebSuggestion(
            mode="web_search",
            reason="sports_schedule_likely",
            confidence="high",
            query=clean_query,
        )

    if current_intent or explicit_search:
        return WebSuggestion(
            mode="web_search",
            reason="current_information_likely",
            confidence="medium",
            query=clean_query,
        )

    return None
