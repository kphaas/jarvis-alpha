from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

MemoryCategory = Literal[
    "preference",
    "person",
    "project",
    "constraint",
    "health",
    "child_profile",
]

MEMORY_CATEGORIES: tuple[MemoryCategory, ...] = (
    "preference",
    "person",
    "project",
    "constraint",
    "health",
    "child_profile",
)

_CONTROL_TEXT = re.compile(
    r"\b(ignore|disregard|override|bypass)\b.{0,80}\b("
    r"system|developer|previous|prior|instruction|policy|safety|guardrail"
    r")\b",
    re.IGNORECASE,
)
_SECRET_TEXT = re.compile(
    r"\b(api[_ -]?key|bearer token|password|private key|secret)\b",
    re.IGNORECASE,
)
_HEALTH_TEXT = re.compile(
    r"\b(health|medical|doctor|medicine|medication|allerg|kidney|emergency)\b",
    re.IGNORECASE,
)
_CHILD_TEXT = re.compile(
    r"\b(ryleigh|sloane|child|daughter|school|teacher|custody)\b",
    re.IGNORECASE,
)
_CONSTRAINT_TEXT = re.compile(
    r"\b(must|never|always|guardrail|approval|approved|not allowed|forbid|blocked)\b",
    re.IGNORECASE,
)
_PREFERENCE_TEXT = re.compile(
    r"\b(prefer|favorite|like|dislike|hate|love|enjoy|avoid)\b",
    re.IGNORECASE,
)
_PROJECT_TEXT = re.compile(
    r"\b(alpha|at-?0|jarvis|helm|forge|family|spark|beacon|warden|keyturner)\b",
    re.IGNORECASE,
)
_PERSON_TEXT = re.compile(
    r"\b(sweta|ken|kenneth|meagan|mom|mother|dad|father|person|relationship)\b",
    re.IGNORECASE,
)


class MemoryFactValidationError(ValueError):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ParsedMemoryCommand:
    fact: str
    category: MemoryCategory


def sanitize_semantic_fact(fact: str) -> str:
    normalized = " ".join(fact.strip().split())
    if not normalized:
        raise MemoryFactValidationError("memory_fact_required")
    if _CONTROL_TEXT.search(normalized):
        raise MemoryFactValidationError("memory_fact_rejected_control_text")
    if _SECRET_TEXT.search(normalized):
        raise MemoryFactValidationError("memory_fact_rejected_secret_text")
    return normalized


def parse_memory_command(prompt: str) -> ParsedMemoryCommand | None:
    stripped = prompt.strip()
    lowered = stripped.lower()
    if not lowered.startswith("/memory"):
        return None

    command_tail = stripped[len("/memory") :]
    if command_tail and not command_tail[0].isspace() and command_tail[0] != ":":
        return None

    remainder = command_tail.lstrip(" :").strip()
    if not remainder:
        raise MemoryFactValidationError("memory_command_fact_required")

    category, fact = _split_optional_category(remainder)
    sanitized = sanitize_semantic_fact(fact)
    return ParsedMemoryCommand(
        fact=sanitized,
        category=category or infer_memory_category(sanitized),
    )


def infer_memory_category(fact: str) -> MemoryCategory:
    if _HEALTH_TEXT.search(fact):
        return "health"
    if _CHILD_TEXT.search(fact):
        return "child_profile"
    if _CONSTRAINT_TEXT.search(fact):
        return "constraint"
    if _PREFERENCE_TEXT.search(fact):
        return "preference"
    if _PROJECT_TEXT.search(fact):
        return "project"
    if _PERSON_TEXT.search(fact):
        return "person"
    return "project"


def memory_save_response_text(
    *,
    saved: bool,
    category: str,
    reason: object = None,
    review_required: object = None,
) -> str:
    if saved:
        if review_required:
            return f"Saved to semantic memory as {category}. Flagged for review."
        return f"Saved to semantic memory as {category}."
    if reason == "cap_reached":
        return "Memory cap reached; nothing saved."
    return "I could not save that memory."


def _split_optional_category(value: str) -> tuple[MemoryCategory | None, str]:
    if value.startswith("["):
        end = value.find("]")
        if end > 1:
            candidate = value[1:end].strip().lower()
            if candidate in MEMORY_CATEGORIES:
                return candidate, value[end + 1 :].lstrip(" :")

    head, separator, tail = value.partition(":")
    candidate = head.strip().lower()
    if separator and candidate in MEMORY_CATEGORIES and tail.strip():
        return candidate, tail.strip()

    first, _, rest = value.partition(" ")
    candidate = first.strip().lower()
    if candidate in MEMORY_CATEGORIES and rest.strip():
        return candidate, rest.strip()

    return None, value
