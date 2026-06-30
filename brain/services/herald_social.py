from __future__ import annotations

import hashlib
import json
import os
import re
from urllib.parse import unquote
from dataclasses import dataclass
from datetime import date
from uuid import UUID
from typing import Literal, Protocol

import asyncpg

from brain.services.internet_scout.gateway_client import InternetScoutGatewayClient
from brain.services.internet_scout.models import GatewaySearchResponse
from brain.services.herald_interaction_ledger import (
    record_herald_interaction,
    record_social_draft_interaction,
)
from brain.services.spark_memory_grounding import (
    SparkMemoryGroundingError,
    load_spark_memory_grounding,
)
from brain.services.spark_personality_memory import (
    fetch_personality_memory,
    personality_memory_context,
    save_personality_memory,
)
from brain.services.spark_voice_ingest import SparkVoiceIngestError


SocialPlatform = Literal["x", "linkedin"]
SocialDraftKind = Literal["post", "reply"]
SocialReplyStyle = Literal["strong_short", "practical", "warm"]
SUPPORTED_PLATFORMS: tuple[SocialPlatform, ...] = ("x", "linkedin")
LINKEDIN_REPLY_STYLES: tuple[SocialReplyStyle, ...] = (
    "strong_short",
    "practical",
    "warm",
)

_WHITESPACE = re.compile(r"\s+")
_BANNED_HYPE = re.compile(
    r"\b(revolutionary|game-changing|next-gen|disruptive|magic)\b",
    re.IGNORECASE,
)
_WRONG_NAME = re.compile(r"\b(AT-0|ATO|At0|at0)\b")
_LINKEDIN_POST_URN = re.compile(r"urn:li:(?:activity|share):\d+")
_LINKEDIN_ACTIVITY_URL = re.compile(r"(?:activity|share)-(\d{8,25})(?:[-/?#]|$)")
DEFAULT_LINKEDIN_TARGET_TOPICS: tuple[str, ...] = (
    "enterprise AI transformation",
    "AI operating model",
    "AI governance and risk",
    "human in the loop AI",
    "private AI infrastructure",
)


class _SearchClient(Protocol):
    async def search(
        self,
        *,
        query: str,
        count: int = 5,
        provider: Literal["auto", "searxng", "brave", "perplexity"] = "auto",
    ) -> GatewaySearchResponse: ...


@dataclass(frozen=True, slots=True)
class SocialDraftResult:
    draft_text: str
    content_hash: str
    voice_score: float
    safety_flags: tuple[str, ...]
    spark_context_hash: str | None


@dataclass(frozen=True, slots=True)
class WeeklyDraftOutcome:
    created: bool
    reason: str
    request_id: UUID | None
    variant_id: UUID | None


@dataclass(frozen=True, slots=True)
class EngagementDraftOutcome:
    created_count: int
    reason: str
    item_ids: tuple[UUID, ...]
    variant_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class EngagementScoutOutcome:
    created_count: int
    skipped_count: int
    reason: str
    item_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class LinkedInMetricOutcome:
    metric_id: UUID
    variant_id: UUID
    engagement_total: int
    engagement_rate: float
    spark_memory_saved: bool
    spark_memory_content: str | None


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
    reply_style: SocialReplyStyle = "practical",
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
            reply_style=reply_style,
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
    if draft_kind == "reply":
        flags.append(f"reply_style_{reply_style}")
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
            "Enterprise AI transformation works when it starts as an operating model: "
            "clear ownership, approval gates, observability, and reversible decisions."
        ),
        (
            "AT0 progress note: I am building private AI infrastructure around memory, "
            "human review, and evidence trails before giving automation more authority."
        ),
        (
            "The enterprise AI lesson I keep coming back to: the hard part is not the model. "
            "It is trust, change management, integration boundaries, and knowing what must stay human-approved."
        ),
        (
            "AT0 is my live lab for enterprise transformation patterns: local-first memory, "
            "operator control, audit records, and practical automation that earns its way into production."
        ),
    )
    week_index = today.isocalendar().week % len(themes)
    return themes[week_index]


def linkedin_engagement_reply_topic(item_text: str) -> str:
    clean = " ".join(item_text.split()).strip()
    return clean[:500]


def linkedin_engagement_slots_due(isodow: int) -> int:
    if isodow < 1 or isodow > 7:
        raise ValueError("isodow must be 1..7")
    if isodow < 3:
        return 1
    if isodow < 5:
        return 2
    return 3


def linkedin_reply_style_from_flags(
    flags: list[str] | tuple[str, ...],
) -> SocialReplyStyle:
    if "reply_style_warm" in flags:
        return "warm"
    if "reply_style_practical" in flags:
        return "practical"
    return "strong_short"


def linkedin_metric_engagement_total(
    *,
    reactions: int,
    comments: int,
    reposts: int,
    profile_clicks: int,
) -> int:
    return (
        max(0, reactions) + max(0, comments) + max(0, reposts) + max(0, profile_clicks)
    )


def linkedin_metric_engagement_rate(
    *, engagement_total: int, impressions: int
) -> float:
    if impressions <= 0:
        return 0.0
    return round(engagement_total / impressions, 4)


def linkedin_metric_memory_content(
    *,
    topic: str,
    draft_kind: SocialDraftKind,
    reply_style: SocialReplyStyle,
    engagement_total: int,
    impressions: int,
    engagement_rate: float,
) -> str | None:
    if engagement_total < 3 and engagement_rate < 0.02:
        return None
    clean_topic = clean_social_topic(topic)[:140]
    rate = f"{engagement_rate:.1%}" if impressions > 0 else "unmeasured reach"
    if draft_kind == "reply":
        return (
            f"LinkedIn replies in {reply_style.replace('_', ' ')} style worked for "
            f"{clean_topic}; result was {engagement_total} engagements at {rate}."
        )[:500]
    return (
        f"LinkedIn posts on {clean_topic} worked; result was "
        f"{engagement_total} engagements at {rate}. Favor this topic pattern."
    )[:500]


def linkedin_target_scout_queries(
    topics: list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    clean_topics = tuple(
        dict.fromkeys(
            clean_social_topic(topic)
            for topic in (topics or DEFAULT_LINKEDIN_TARGET_TOPICS)
            if topic.strip()
        )
    )
    return tuple(
        f"LinkedIn posts {topic} enterprise AI CIO business transformation"
        for topic in clean_topics
    )


def linkedin_post_urn_from_url(url: str | None) -> str | None:
    text = unquote((url or "").strip())
    if not text:
        return None
    urn = _LINKEDIN_POST_URN.search(text)
    if urn:
        return urn.group(0)[:200]
    activity = _LINKEDIN_ACTIVITY_URL.search(text)
    if activity:
        return f"urn:li:activity:{activity.group(1)}"
    return None


async def create_weekly_linkedin_draft_if_due(
    conn: asyncpg.Connection,
    *,
    actor_sub: str,
    actor_type: str = "service",
) -> WeeklyDraftOutcome:
    async with conn.transaction():
        active_variant_id = await conn.fetchval(
            """
            SELECT v.id
            FROM public.alpha_herald_social_draft_variants v
            JOIN public.alpha_herald_social_draft_requests r
              ON r.id = v.request_id
            WHERE r.campaign = 'linkedin-weekly-brand'
              AND v.platform = 'linkedin'
              AND v.status IN ('needs_review', 'approved')
              AND v.publish_status NOT IN ('manual_published', 'linkedin_published')
            ORDER BY v.created_at DESC
            LIMIT 1
            """
        )
        if active_variant_id is not None:
            return WeeklyDraftOutcome(False, "active_weekly_draft_exists", None, None)

        cadence = await conn.fetchrow(
            """
            SELECT current_date AS today,
                   max(v.published_at) FILTER (
                       WHERE v.platform = 'linkedin'
                         AND v.publish_status IN (
                             'manual_published', 'linkedin_published'
                         )
                   ) AS last_published_at
            FROM public.alpha_herald_social_draft_variants v
            """
        )
        today = cadence["today"]
        last_published_at = cadence["last_published_at"]
        if last_published_at is not None and today < last_published_at.date():
            return WeeklyDraftOutcome(False, "not_due", None, None)
        if (
            last_published_at is not None
            and (today - last_published_at.date()).days < 7
        ):
            return WeeklyDraftOutcome(False, "not_due", None, None)

        profile = await conn.fetchrow(
            """
            SELECT platform, account_label, audience_notes, voice_rules,
                   safety_rules, max_chars, profile_version
            FROM public.alpha_herald_social_platform_profiles
            WHERE active = true
              AND platform = 'linkedin'
            """
        )
        if profile is None:
            return WeeklyDraftOutcome(False, "linkedin_profile_missing", None, None)

        topic = linkedin_weekly_topic(today)
        spark_context, spark_meta = await load_herald_spark_context(conn)
        request_id = await conn.fetchval(
            """
            INSERT INTO public.alpha_herald_social_draft_requests (
                topic, campaign, account_label, requested_by, draft_kind
            )
            VALUES ($1, 'linkedin-weekly-brand', 'AT0', $2, 'post')
            RETURNING id
            """,
            topic,
            actor_sub,
        )
        await _record_service_event(
            conn,
            request_id=request_id,
            variant_id=None,
            event_type="request_created",
            actor_sub=actor_sub,
            actor_type=actor_type,
            payload={
                "draft_kind": "post",
                "platforms": ["linkedin"],
                "spark_input": {
                    "topic": topic,
                    "context_hash": spark_meta.get("context_hash"),
                    "context_available": spark_meta.get("context_available"),
                },
                "trigger": "weekly_auto",
            },
        )

        draft = create_social_draft(
            topic=topic,
            platform="linkedin",
            max_chars=int(profile["max_chars"]),
            spark_context=spark_context,
        )
        repeat_of = await conn.fetchval(
            """
            SELECT id
            FROM public.alpha_herald_social_draft_variants
            WHERE platform = 'linkedin'
              AND content_hash = $1
            ORDER BY created_at DESC
            LIMIT 1
            """,
            draft.content_hash,
        )
        safety_flags = list(draft.safety_flags)
        if repeat_of is not None:
            safety_flags.append("possible_repeat")
        variant_id = await conn.fetchval(
            """
            INSERT INTO public.alpha_herald_social_draft_variants (
                request_id, platform, account_label, draft_text, content_hash,
                profile_version, audience_notes, voice_rules, safety_rules,
                voice_score, safety_flags, repeat_of_variant_id
            )
            VALUES (
                $1, 'linkedin', 'AT0', $2, $3, $4, $5,
                $6::text[], $7::text[], $8, $9::text[], $10
            )
            RETURNING id
            """,
            request_id,
            draft.draft_text,
            draft.content_hash,
            int(profile["profile_version"]),
            profile["audience_notes"],
            list(profile["voice_rules"]),
            list(profile["safety_rules"]),
            draft.voice_score,
            safety_flags,
            repeat_of,
        )
        await _record_service_event(
            conn,
            request_id=request_id,
            variant_id=variant_id,
            event_type="variant_created",
            actor_sub=actor_sub,
            actor_type=actor_type,
            payload={
                "platform": "linkedin",
                "draft_kind": "post",
                "profile_version": int(profile["profile_version"]),
                "repeat": repeat_of is not None,
                "spark_input": {
                    "context_hash": draft.spark_context_hash,
                    "context_available": bool(draft.spark_context_hash),
                },
                "spark_output": {
                    "content_hash": draft.content_hash,
                    "draft_engine": "herald_social_spark_v1",
                },
                "trigger": "weekly_auto",
            },
        )
        return WeeklyDraftOutcome(True, "created", request_id, variant_id)


async def draft_linkedin_engagement_replies_if_due(
    conn: asyncpg.Connection,
    *,
    actor_sub: str,
    actor_type: str = "service",
    weekly_limit: int = 3,
) -> EngagementDraftOutcome:
    async with conn.transaction():
        cadence = await conn.fetchrow(
            """
            SELECT current_date AS today,
                   EXTRACT(ISODOW FROM current_date)::int AS isodow
            """
        )
        slots_due = min(weekly_limit, linkedin_engagement_slots_due(cadence["isodow"]))
        created_this_week = await conn.fetchval(
            """
            SELECT count(*)::int
            FROM public.alpha_herald_social_draft_variants v
            JOIN public.alpha_herald_social_draft_requests r
              ON r.id = v.request_id
            WHERE r.campaign = 'linkedin-engagement-inbox'
              AND r.draft_kind = 'reply'
              AND v.platform = 'linkedin'
              AND v.created_at >= date_trunc('week', now())
              AND (
                  v.status IN ('needs_review', 'approved')
                  OR v.publish_status IN ('manual_published', 'linkedin_published')
              )
            """
        )
        remaining = min(weekly_limit - created_this_week, slots_due - created_this_week)
        if remaining <= 0:
            return EngagementDraftOutcome(0, "quota_satisfied", (), ())

        profile = await conn.fetchrow(
            """
            SELECT platform, account_label, audience_notes, voice_rules,
                   safety_rules, max_chars, profile_version
            FROM public.alpha_herald_social_platform_profiles
            WHERE active = true
              AND platform = 'linkedin'
            """
        )
        if profile is None:
            return EngagementDraftOutcome(0, "linkedin_profile_missing", (), ())

        items = await conn.fetch(
            """
            SELECT id, author_name, item_text, item_url
            FROM public.alpha_herald_social_engagement_items
            WHERE status = 'needs_reply'
            ORDER BY discovered_at ASC, created_at ASC
            LIMIT $1
            FOR UPDATE SKIP LOCKED
            """,
            remaining,
        )
        if not items:
            return EngagementDraftOutcome(0, "no_targets", (), ())

        spark_context, spark_meta = await load_herald_spark_context(conn)
        item_ids: list[UUID] = []
        variant_ids: list[UUID] = []
        for item in items:
            topic = linkedin_engagement_reply_topic(str(item["item_text"]))
            request_id = await conn.fetchval(
                """
                INSERT INTO public.alpha_herald_social_draft_requests (
                    topic, source_url, campaign, account_label, requested_by,
                    draft_kind, engagement_author
                )
                VALUES (
                    $1, $2, 'linkedin-engagement-inbox', 'AT0', $3, 'reply', $4
                )
                RETURNING id
                """,
                topic,
                item["item_url"],
                actor_sub,
                str(item["author_name"]),
            )
            await _record_service_event(
                conn,
                request_id=request_id,
                variant_id=None,
                event_type="request_created",
                actor_sub=actor_sub,
                actor_type=actor_type,
                payload={
                    "draft_kind": "reply",
                    "platforms": ["linkedin"],
                    "engagement_item_id": str(item["id"]),
                    "spark_input": {
                        "topic": topic,
                        "context_hash": spark_meta.get("context_hash"),
                        "context_available": spark_meta.get("context_available"),
                    },
                    "trigger": "engagement_scheduler",
                },
            )
            draft = create_social_draft(
                topic=topic,
                platform="linkedin",
                max_chars=int(profile["max_chars"]),
                draft_kind="reply",
                engagement_author=str(item["author_name"]),
                reply_style="strong_short",
                spark_context=spark_context,
            )
            repeat_of = await conn.fetchval(
                """
                SELECT id
                FROM public.alpha_herald_social_draft_variants
                WHERE platform = 'linkedin'
                  AND content_hash = $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                draft.content_hash,
            )
            safety_flags = list(draft.safety_flags)
            if repeat_of is not None:
                safety_flags.append("possible_repeat")
            variant_id = await conn.fetchval(
                """
                INSERT INTO public.alpha_herald_social_draft_variants (
                    request_id, platform, account_label, draft_text, content_hash,
                    profile_version, audience_notes, voice_rules, safety_rules,
                    voice_score, safety_flags, repeat_of_variant_id
                )
                VALUES (
                    $1, 'linkedin', 'AT0', $2, $3, $4, $5,
                    $6::text[], $7::text[], $8, $9::text[], $10
                )
                RETURNING id
                """,
                request_id,
                draft.draft_text,
                draft.content_hash,
                int(profile["profile_version"]),
                profile["audience_notes"],
                list(profile["voice_rules"]),
                list(profile["safety_rules"]),
                draft.voice_score,
                safety_flags,
                repeat_of,
            )
            await conn.execute(
                """
                UPDATE public.alpha_herald_social_engagement_items
                SET status = 'draft_created',
                    reply_variant_id = $2,
                    updated_at = now()
                WHERE id = $1
                """,
                item["id"],
                variant_id,
            )
            await _record_service_event(
                conn,
                request_id=request_id,
                variant_id=variant_id,
                event_type="variant_created",
                actor_sub=actor_sub,
                actor_type=actor_type,
                payload={
                    "platform": "linkedin",
                    "draft_kind": "reply",
                    "engagement_item_id": str(item["id"]),
                    "profile_version": int(profile["profile_version"]),
                    "repeat": repeat_of is not None,
                    "spark_input": {
                        "context_hash": draft.spark_context_hash,
                        "context_available": bool(draft.spark_context_hash),
                    },
                    "spark_output": {
                        "content_hash": draft.content_hash,
                        "draft_engine": "herald_social_spark_v1",
                    },
                    "trigger": "engagement_scheduler",
                },
            )
            item_ids.append(item["id"])
            variant_ids.append(variant_id)

    return EngagementDraftOutcome(
        len(variant_ids),
        "created" if variant_ids else "no_targets",
        tuple(item_ids),
        tuple(variant_ids),
    )


async def record_linkedin_metric_snapshot(
    conn: asyncpg.Connection,
    *,
    variant_id: UUID,
    actor_sub: str,
    actor_type: str,
    engagement_item_id: UUID | None = None,
    metric_source: Literal["manual", "linkedin_api"] = "manual",
    impressions: int = 0,
    reactions: int = 0,
    comments: int = 0,
    reposts: int = 0,
    profile_clicks: int = 0,
    captured_on: date | None = None,
    notes: str | None = None,
) -> LinkedInMetricOutcome:
    engagement_total = linkedin_metric_engagement_total(
        reactions=reactions,
        comments=comments,
        reposts=reposts,
        profile_clicks=profile_clicks,
    )
    engagement_rate = linkedin_metric_engagement_rate(
        engagement_total=engagement_total,
        impressions=impressions,
    )
    async with conn.transaction():
        draft = await conn.fetchrow(
            """
            SELECT v.id, v.content_hash, v.safety_flags, r.topic, r.draft_kind
            FROM public.alpha_herald_social_draft_variants v
            JOIN public.alpha_herald_social_draft_requests r
              ON r.id = v.request_id
            WHERE v.id = $1
              AND v.platform = 'linkedin'
            """,
            variant_id,
        )
        if draft is None:
            raise ValueError("linkedin_metric_variant_not_found")
        metric_id = await conn.fetchval(
            """
            INSERT INTO public.alpha_herald_social_metric_snapshots (
                variant_id, engagement_item_id, metric_source, impressions,
                reactions, comments, reposts, profile_clicks, captured_on,
                recorded_by, notes
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8,
                COALESCE($9, current_date), $10, $11
            )
            RETURNING id
            """,
            variant_id,
            engagement_item_id,
            metric_source,
            impressions,
            reactions,
            comments,
            reposts,
            profile_clicks,
            captured_on,
            actor_sub,
            notes.strip() if notes else None,
        )
        await record_herald_interaction(
            conn,
            channel="linkedin",
            interaction_kind="metric",
            direction="internal",
            lifecycle_event="metric_recorded",
            status="recorded",
            primary_ref_type="social_metric_snapshot",
            primary_ref_id=metric_id,
            secondary_ref_type="social_draft_variant",
            secondary_ref_id=variant_id,
            actor_sub=actor_sub,
            actor_type=actor_type,
            event_metadata={
                "metric_source": metric_source,
                "engagement_total": engagement_total,
                "engagement_rate": engagement_rate,
            },
        )

    reply_style = linkedin_reply_style_from_flags(list(draft["safety_flags"] or []))
    memory = linkedin_metric_memory_content(
        topic=str(draft["topic"]),
        draft_kind=str(draft["draft_kind"]),  # type: ignore[arg-type]
        reply_style=reply_style,
        engagement_total=engagement_total,
        impressions=impressions,
        engagement_rate=engagement_rate,
    )
    spark_saved = False
    if memory:
        try:
            async with conn.transaction():
                result = await save_personality_memory(
                    conn,
                    principal_id=os.environ.get("HERALD_SPARK_PRINCIPAL_ID", "ken"),
                    kind="preference",
                    content=memory,
                    source="spark_feedback",
                    evidence_ref_hash=str(draft["content_hash"]),
                    approved_by=actor_sub,
                    importance_score=0.72,
                )
                spark_saved = bool(result.get("saved"))
                if spark_saved:
                    await record_herald_interaction(
                        conn,
                        channel="linkedin",
                        interaction_kind="metric",
                        direction="internal",
                        lifecycle_event="metric_spark_memory_saved",
                        status="saved",
                        primary_ref_type="social_metric_snapshot",
                        primary_ref_id=metric_id,
                        secondary_ref_type="social_draft_variant",
                        secondary_ref_id=variant_id,
                        actor_sub=actor_sub,
                        actor_type=actor_type,
                        event_metadata={"memory_kind": "preference"},
                    )
        except Exception:
            spark_saved = False

    return LinkedInMetricOutcome(
        metric_id=metric_id,
        variant_id=variant_id,
        engagement_total=engagement_total,
        engagement_rate=engagement_rate,
        spark_memory_saved=spark_saved,
        spark_memory_content=memory if spark_saved else None,
    )


async def load_linkedin_operator_dashboard(
    conn: asyncpg.Connection,
) -> dict[str, object]:
    cadence = await conn.fetchrow(
        """
        SELECT current_date AS today,
               max(v.published_at) FILTER (
                   WHERE v.platform = 'linkedin'
                     AND v.publish_status IN ('manual_published', 'linkedin_published')
               ) AS last_published_at,
               count(*) FILTER (
                   WHERE v.platform = 'linkedin'
                     AND v.status = 'needs_review'
               )::int AS approval_backlog,
               count(*) FILTER (
                   WHERE v.platform = 'linkedin'
                     AND v.status IN ('needs_review', 'approved')
                     AND v.publish_status NOT IN ('manual_published', 'linkedin_published')
                     AND r.campaign = 'linkedin-weekly-brand'
               )::int AS active_weekly_drafts
        FROM public.alpha_herald_social_draft_variants v
        JOIN public.alpha_herald_social_draft_requests r
          ON r.id = v.request_id
        """
    )
    created_comments = await conn.fetchval(
        """
        SELECT count(*)::int
        FROM public.alpha_herald_social_draft_variants v
        JOIN public.alpha_herald_social_draft_requests r
          ON r.id = v.request_id
        WHERE r.campaign = 'linkedin-engagement-inbox'
          AND r.draft_kind = 'reply'
          AND v.platform = 'linkedin'
          AND v.created_at >= date_trunc('week', now())
          AND (
              v.status IN ('needs_review', 'approved')
              OR v.publish_status IN ('manual_published', 'linkedin_published')
          )
        """
    )
    isodow = int(await conn.fetchval("SELECT EXTRACT(ISODOW FROM current_date)::int"))
    targets_ready = int(
        await conn.fetchval(
            """
            SELECT count(*)::int
            FROM public.alpha_herald_social_engagement_items
            WHERE status = 'needs_reply'
            """
        )
        or 0
    )
    active_thought_leaders = int(
        await conn.fetchval(
            """
            SELECT count(*)::int
            FROM public.alpha_herald_thought_leader_targets
            WHERE status = 'active'
            """
        )
        or 0
    )
    metric_snapshots = int(
        await conn.fetchval(
            """
            SELECT count(*)::int
            FROM public.alpha_herald_social_metric_snapshots
            WHERE created_at >= now() - interval '30 days'
            """
        )
        or 0
    )
    best_topic = await conn.fetchval(
        """
        SELECT r.topic
        FROM public.alpha_herald_social_metric_snapshots m
        JOIN public.alpha_herald_social_draft_variants v ON v.id = m.variant_id
        JOIN public.alpha_herald_social_draft_requests r ON r.id = v.request_id
        GROUP BY r.topic
        ORDER BY
          CASE
            WHEN sum(m.impressions) > 0
            THEN (
              sum(m.reactions + m.comments + m.reposts + m.profile_clicks)::float
              / sum(m.impressions)
            )
            ELSE sum(m.reactions + m.comments + m.reposts + m.profile_clicks)::float
          END DESC,
          max(m.created_at) DESC
        LIMIT 1
        """
    )
    best_reply_style = await conn.fetchval(
        """
        SELECT CASE
                 WHEN 'reply_style_warm' = ANY(v.safety_flags) THEN 'warm'
                 WHEN 'reply_style_practical' = ANY(v.safety_flags) THEN 'practical'
                 ELSE 'strong_short'
               END AS reply_style
        FROM public.alpha_herald_social_metric_snapshots m
        JOIN public.alpha_herald_social_draft_variants v ON v.id = m.variant_id
        JOIN public.alpha_herald_social_draft_requests r ON r.id = v.request_id
        WHERE r.draft_kind = 'reply'
        GROUP BY reply_style
        ORDER BY sum(m.reactions + m.comments + m.reposts + m.profile_clicks) DESC,
                 max(m.created_at) DESC
        LIMIT 1
        """
    )
    today = cadence["today"]
    last_published_at = cadence["last_published_at"]
    post_due = bool(cadence["active_weekly_drafts"] == 0)
    if last_published_at is not None:
        post_due = post_due and (today - last_published_at.date()).days >= 7
    comments_due = max(
        0,
        min(3, linkedin_engagement_slots_due(isodow)) - int(created_comments or 0),
    )
    return {
        "post_due": post_due,
        "comments_due": comments_due,
        "best_topic": best_topic or linkedin_weekly_topic(today),
        "best_reply_style": best_reply_style or "strong_short",
        "targets_ready": targets_ready,
        "approval_backlog": int(cadence["approval_backlog"] or 0),
        "active_thought_leaders": active_thought_leaders,
        "metric_snapshots_30d": metric_snapshots,
    }


async def scout_linkedin_engagement_targets(
    conn: asyncpg.Connection,
    *,
    actor_sub: str,
    topics: list[str] | tuple[str, ...] | None = None,
    per_topic: int = 2,
    max_targets: int = 6,
    search_client: _SearchClient | None = None,
) -> EngagementScoutOutcome:
    queries = linkedin_target_scout_queries(topics)
    if not queries:
        return EngagementScoutOutcome(0, 0, "no_topics", ())

    client = search_client or InternetScoutGatewayClient()
    item_ids: list[UUID] = []
    skipped = 0
    per_topic = max(1, min(per_topic, 5))
    max_targets = max(1, min(max_targets, 12))
    created_by = (actor_sub or "unknown")[:160]

    for query in queries:
        if len(item_ids) >= max_targets:
            break
        response = await client.search(query=query, count=per_topic, provider="auto")
        for result in response.results:
            if len(item_ids) >= max_targets:
                break
            if result.risk_markers:
                skipped += 1
                continue
            url = result.url.strip()
            if not url:
                skipped += 1
                continue
            provider_item_urn = f"herald:scout:{hash_social_draft(url)[:16]}"
            provider_post_urn = linkedin_post_urn_from_url(url)
            row = await conn.fetchrow(
                """
                INSERT INTO public.alpha_herald_social_engagement_items (
                    source, account_label, provider_item_urn, provider_post_urn,
                    item_url, author_name, item_text, created_by
                )
                VALUES ('manual', 'AT0', $1, $2, $3, $4, $5, $6)
                ON CONFLICT (provider_item_urn) WHERE provider_item_urn IS NOT NULL
                DO UPDATE SET
                    provider_post_urn = COALESCE(
                        EXCLUDED.provider_post_urn,
                        alpha_herald_social_engagement_items.provider_post_urn
                    ),
                    item_url = EXCLUDED.item_url,
                    updated_at = now()
                RETURNING id
                """,
                provider_item_urn,
                provider_post_urn,
                _fit(url, 500),
                _scout_author_name(result.title, result.host),
                _scout_item_text(result.title, result.description, result.host),
                created_by,
            )
            if row is None:
                skipped += 1
                continue
            item_ids.append(row["id"])
            await record_herald_interaction(
                conn,
                channel="linkedin",
                interaction_kind="engagement",
                direction="inbound",
                lifecycle_event="engagement_scouted",
                status="needs_reply",
                primary_ref_type="social_engagement_item",
                primary_ref_id=row["id"],
                actor_sub=created_by,
                actor_type="service",
                related_refs={"provider_item_urn": provider_item_urn},
                event_metadata={
                    "source": "gateway_scout",
                    "query_hash": response.query_hash,
                    "host": result.host,
                    "provider_post_urn_present": provider_post_urn is not None,
                },
            )

    return EngagementScoutOutcome(
        len(item_ids),
        skipped,
        "created" if item_ids else "no_new_targets",
        tuple(item_ids),
    )


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
    reply_style: SocialReplyStyle,
    max_chars: int,
    spark_context: str | None = None,
) -> str:
    spark_line = _spark_reply_line(spark_context, reply_style=reply_style)
    if reply_style == "strong_short":
        template = (
            "Strong point. AI governance is not overhead; it is the operating "
            "model that lets teams move faster without losing trust, auditability, "
            "or accountability."
        )
    elif reply_style == "warm":
        template = (
            "Agree with this framing, {author}. The organizations that win with AI "
            "will be the ones that make trust, accountability, and review trails part "
            "of the operating model from the start.\n\n"
            "{spark_line}"
            "That is where AI moves from experiment to enterprise capability."
        )
    else:
        template = (
            "This is the right enterprise AI question, {author}: not just whether AI "
            "can automate work, but whether leaders can inspect, govern, and trust it "
            "at scale.\n\n"
            "{spark_line}"
            "That is the bar I keep coming back to: useful autonomy with a clear human "
            "approval trail."
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


def _scout_author_name(title: str | None, host: str) -> str:
    clean = _WHITESPACE.sub(" ", (title or host or "LinkedIn target").strip())
    return _fit(clean, 160)


def _scout_item_text(title: str | None, description: str, host: str) -> str:
    parts = [
        _WHITESPACE.sub(" ", part.strip())
        for part in (title or "", description, f"Source host: {host}")
        if part.strip()
    ]
    return _fit("\n\n".join(parts), 1200)


def _spark_public_line(spark_context: str | None) -> str:
    if not spark_context:
        return ""
    return (
        "I am keeping the public bar practical: specific claims, low hype, "
        "and a review trail before anything acts on my behalf.\n\n"
    )


def _spark_reply_line(
    spark_context: str | None,
    *,
    reply_style: SocialReplyStyle,
) -> str:
    if not spark_context:
        return ""
    if reply_style == "strong_short":
        return ""
    return (
        "The useful posture is practical, low-hype, and grounded in reviewable "
        "systems.\n\n"
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


async def _record_service_event(
    conn: asyncpg.Connection,
    *,
    request_id: UUID,
    variant_id: UUID | None,
    event_type: str,
    actor_sub: str,
    actor_type: str,
    payload: dict[str, object],
) -> None:
    await conn.execute(
        """
        INSERT INTO public.alpha_herald_social_draft_events (
            request_id, variant_id, event_type, actor_sub, actor_type, event_payload
        )
        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
        """,
        request_id,
        variant_id,
        event_type,
        actor_sub,
        actor_type,
        json.dumps(payload, sort_keys=True),
    )
    await record_social_draft_interaction(
        conn,
        request_id=request_id,
        variant_id=variant_id,
        event_type=event_type,
        actor_sub=actor_sub,
        actor_type=actor_type,
        payload=payload,
    )
