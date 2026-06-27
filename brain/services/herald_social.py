from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

import asyncpg

from brain.services.spark_memory_grounding import (
    SparkMemoryGroundingError,
    load_spark_memory_grounding,
)
from brain.services.spark_personality_memory import (
    fetch_personality_memory,
    personality_memory_context,
)
from brain.services.spark_voice_ingest import SparkVoiceIngestError


SocialPlatform = Literal["x", "linkedin"]
SocialDraftKind = Literal["post", "reply"]
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
    spark_context_hash: str | None


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
    draft_kind: SocialDraftKind = "post",
    engagement_author: str | None = None,
    spark_context: str | None = None,
) -> SocialDraftResult:
    clean_topic = clean_social_topic(topic)
    clean_author = _clean_author(engagement_author)
    clean_spark_context = _clean_spark_context(spark_context)
    if draft_kind == "reply":
        if platform != "linkedin":
            raise ValueError("reply_drafts_linkedin_only")
        draft = _linkedin_reply_draft(
            clean_topic,
            engagement_author=clean_author or "there",
            max_chars=max_chars,
            spark_context=clean_spark_context,
        )
    elif platform == "x":
        draft = _x_draft(clean_topic, max_chars=max_chars)
    else:
        draft = _linkedin_draft(
            clean_topic,
            max_chars=max_chars,
            spark_context=clean_spark_context,
        )
    flags = list(_safety_flags(draft))
    flags.extend(("draft_only_no_publish", "human_review_required"))
    if clean_spark_context:
        flags.append("spark_context_used")
    return SocialDraftResult(
        draft_text=draft,
        content_hash=hash_social_draft(draft),
        voice_score=_voice_score(draft, flags),
        safety_flags=tuple(dict.fromkeys(flags)),
        spark_context_hash=hash_social_draft(clean_spark_context)
        if clean_spark_context
        else None,
    )


def hash_social_draft(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def linkedin_weekly_topic(today: date) -> str:
    themes = (
        (
            "Owned AI should earn trust through operational proof: clear logs, "
            "human approvals, and reversible decisions before automation."
        ),
        (
            "A useful personal AI brand is not about spectacle. It is about "
            "systems that remember context, respect boundaries, and make the "
            "next real-world action safer."
        ),
        (
            "The AT0 build is a bet that privacy and capability can move together: "
            "local-first memory, explicit review gates, and public claims backed by evidence."
        ),
        (
            "Weekly build note: I am treating autonomy as a control problem first. "
            "The system should suggest, explain, wait for approval, then keep an audit trail."
        ),
    )
    week_index = today.isocalendar().week % len(themes)
    return themes[week_index]


def _x_draft(topic: str, *, max_chars: int) -> str:
    template = (
        "AT0 is private AI for real life, running on owned hardware.\n\n"
        "{topic}\n\n"
        "Memory that never resets. Autonomy you control."
    )
    return _fit(template.format(topic=topic), max_chars)


async def load_herald_spark_context(
    conn: asyncpg.Connection,
    *,
    principal_id: str | None = None,
) -> tuple[str, dict[str, object]]:
    principal = principal_id or os.environ.get("HERALD_SPARK_PRINCIPAL_ID") or "ken"
    parts: list[str] = []
    meta: dict[str, object] = {"principal_id": principal}

    try:
        rows = await fetch_personality_memory(conn, principal, limit=8)
    except Exception:
        rows = []
    memory = personality_memory_context(rows, max_lines=8)
    if memory:
        parts.append(memory)
    meta["personality_memory_rows"] = len(rows)

    try:
        grounding = load_spark_memory_grounding(principal_id=principal)
    except (SparkMemoryGroundingError, SparkVoiceIngestError, OSError):
        grounding = None
    if grounding is not None:
        parts.append(grounding.to_context_block())
    meta["grounding_available"] = grounding is not None

    context = _clean_spark_context("\n".join(parts))
    meta["context_hash"] = hash_social_draft(context) if context else None
    meta["context_available"] = bool(context)
    return context, meta


def _linkedin_draft(
    topic: str,
    *,
    max_chars: int,
    spark_context: str | None = None,
) -> str:
    spark_line = _spark_public_line(spark_context)
    template = (
        'I am building AT0 ("Auto") as private AI infrastructure for real life.\n\n'
        "{topic}\n\n"
        "{spark_line}"
        "The point is simple: memory that never resets, autonomy you can inspect, "
        "and systems that run on hardware you control.\n\n"
        "Current posture: draft first, human approved, no public action without review."
    )
    return _fit(template.format(topic=topic, spark_line=spark_line), max_chars)


def _linkedin_reply_draft(
    topic: str,
    *,
    engagement_author: str,
    max_chars: int,
    spark_context: str | None = None,
) -> str:
    spark_line = _spark_reply_line(spark_context)
    template = (
        "Thanks {author} - this is the part I keep coming back to.\n\n"
        "{topic}\n\n"
        "{spark_line}"
        "For me, the useful bar is whether the system leaves a clear trail: what it saw, "
        "what it suggested, what a human approved, and what changed afterward."
    )
    return _fit(
        template.format(author=engagement_author, topic=topic, spark_line=spark_line),
        max_chars,
    )


def _clean_author(engagement_author: str | None) -> str | None:
    if not engagement_author:
        return None
    clean = _WHITESPACE.sub(" ", engagement_author.strip())
    if not clean:
        return None
    return clean[:120]


def _clean_spark_context(spark_context: str | None) -> str:
    clean = _WHITESPACE.sub(" ", (spark_context or "").strip())
    return clean[:1200]


def _spark_public_line(spark_context: str | None) -> str:
    if not spark_context:
        return ""
    return (
        "I am keeping the public bar practical: specific claims, low hype, "
        "and a review trail before anything acts on my behalf.\n\n"
    )


def _spark_reply_line(spark_context: str | None) -> str:
    if not spark_context:
        return ""
    return (
        "That matches the voice I want here: practical, low-hype, and grounded "
        "in reviewable systems.\n\n"
    )


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
