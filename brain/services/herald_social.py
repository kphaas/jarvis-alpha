from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal


SocialPlatform = Literal["x", "linkedin"]
SUPPORTED_PLATFORMS: tuple[SocialPlatform, ...] = ("x", "linkedin")

_WHITESPACE = re.compile(r"\s+")
_BANNED_HYPE = re.compile(
    r"\b(revolutionary|game-changing|next-gen|disruptive|magic)\b",
    re.IGNORECASE,
)
_WRONG_NAME = re.compile(r"\b(AT-0|ATO|At0|at0)\b")


@dataclass(frozen=True, slots=True)
class SocialDraftResult:
    draft_text: str
    content_hash: str
    voice_score: float
    safety_flags: tuple[str, ...]


def clean_social_topic(topic: str) -> str:
    clean = _WHITESPACE.sub(" ", topic.strip())
    if len(clean) < 3:
        raise ValueError("topic_too_short")
    return clean[:500]


def normalize_platforms(platforms: list[str] | None) -> tuple[SocialPlatform, ...]:
    if not platforms:
        return SUPPORTED_PLATFORMS
    normalized: list[SocialPlatform] = []
    for platform in platforms:
        clean = platform.strip().lower()
        if clean not in SUPPORTED_PLATFORMS:
            raise ValueError(f"unsupported_platform:{clean or 'blank'}")
        if clean not in normalized:
            normalized.append(clean)  # type: ignore[arg-type]
    return tuple(normalized)


def create_social_draft(
    *,
    topic: str,
    platform: SocialPlatform,
    max_chars: int,
) -> SocialDraftResult:
    clean_topic = clean_social_topic(topic)
    if platform == "x":
        draft = _x_draft(clean_topic, max_chars=max_chars)
    else:
        draft = _linkedin_draft(clean_topic, max_chars=max_chars)
    flags = list(_safety_flags(draft))
    flags.extend(("draft_only_no_publish", "human_review_required"))
    return SocialDraftResult(
        draft_text=draft,
        content_hash=hash_social_draft(draft),
        voice_score=_voice_score(draft, flags),
        safety_flags=tuple(dict.fromkeys(flags)),
    )


def hash_social_draft(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _x_draft(topic: str, *, max_chars: int) -> str:
    template = (
        "AT0 is private AI for real life, running on owned hardware.\n\n"
        "{topic}\n\n"
        "Memory that never resets. Autonomy you control."
    )
    return _fit(template.format(topic=topic), max_chars)


def _linkedin_draft(topic: str, *, max_chars: int) -> str:
    template = (
        'I am building AT0 ("Auto") as private AI infrastructure for real life.\n\n'
        "{topic}\n\n"
        "The point is simple: memory that never resets, autonomy you can inspect, "
        "and systems that run on hardware you control.\n\n"
        "Current posture: draft first, human approved, no public action without review."
    )
    return _fit(template.format(topic=topic), max_chars)


def _fit(text: str, max_chars: int) -> str:
    clean = text.strip()
    if len(clean) <= max_chars:
        return clean
    suffix = "..."
    return clean[: max(0, max_chars - len(suffix))].rstrip() + suffix


def _safety_flags(text: str) -> tuple[str, ...]:
    flags: list[str] = []
    if _BANNED_HYPE.search(text):
        flags.append("hype_language")
    if _WRONG_NAME.search(text):
        flags.append("brand_name_violation")
    if "planned" in text.lower():
        flags.append("planned_claim_review")
    return tuple(flags)


def _voice_score(text: str, flags: list[str]) -> float:
    score = 0.92
    if len(text.split()) > 120:
        score -= 0.05
    if "hype_language" in flags:
        score -= 0.18
    if "brand_name_violation" in flags:
        score -= 0.25
    return max(0.0, round(score, 2))
