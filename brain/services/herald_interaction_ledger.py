from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

import asyncpg

Channel = Literal["email", "social", "linkedin", "x"]
InteractionKind = Literal[
    "message", "engagement", "draft", "approval", "outbound", "metric"
]
Direction = Literal["inbound", "outbound", "internal"]


async def record_herald_interaction(
    conn: asyncpg.Connection,
    *,
    channel: Channel,
    interaction_kind: InteractionKind,
    direction: Direction,
    lifecycle_event: str,
    status: str,
    primary_ref_type: str,
    primary_ref_id: str | UUID,
    actor_sub: str | None = None,
    actor_type: str | None = None,
    account_label: str = "AT0",
    secondary_ref_type: str | None = None,
    secondary_ref_id: str | UUID | None = None,
    related_refs: dict[str, Any] | None = None,
    event_metadata: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO public.alpha_herald_interaction_ledger (
            channel, interaction_kind, direction, lifecycle_event, status,
            account_label, primary_ref_type, primary_ref_id,
            secondary_ref_type, secondary_ref_id, actor_sub, actor_type,
            related_refs, event_metadata
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8,
            $9, $10, $11, $12, $13::jsonb, $14::jsonb
        )
        """,
        channel,
        interaction_kind,
        direction,
        _clean(lifecycle_event, "event")[:120],
        _clean(status, "unknown")[:80],
        _clean(account_label, "AT0")[:80],
        _clean(primary_ref_type, "unknown")[:80],
        _clean(str(primary_ref_id), "unknown")[:240],
        _clean(secondary_ref_type, "unknown")[:80] if secondary_ref_type else None,
        _clean(str(secondary_ref_id), "unknown")[:240] if secondary_ref_id else None,
        _clean(actor_sub, "system")[:160],
        _clean(actor_type, "service")[:80],
        json.dumps(related_refs or {}, default=str, sort_keys=True),
        json.dumps(event_metadata or {}, default=str, sort_keys=True),
    )


async def record_social_draft_interaction(
    conn: asyncpg.Connection,
    *,
    request_id: UUID,
    variant_id: UUID | None,
    event_type: str,
    actor_sub: str,
    actor_type: str,
    payload: dict[str, object],
) -> None:
    primary_type = "social_draft_variant" if variant_id else "social_draft_request"
    primary_id = variant_id or request_id
    await record_herald_interaction(
        conn,
        channel=_social_channel(event_type, payload),
        interaction_kind=_social_kind(event_type),
        direction="outbound"
        if "publish" in event_type or "published" in event_type
        else "internal",
        lifecycle_event=event_type,
        status=event_type.removeprefix("variant_"),
        primary_ref_type=primary_type,
        primary_ref_id=primary_id,
        secondary_ref_type="social_draft_request" if variant_id else None,
        secondary_ref_id=request_id if variant_id else None,
        actor_sub=actor_sub,
        actor_type=actor_type,
        related_refs={
            "request_id": str(request_id),
            "variant_id": str(variant_id) if variant_id else None,
        },
        event_metadata=_social_metadata(payload),
    )


def _clean(value: str | None, fallback: str) -> str:
    clean = " ".join((value or fallback).strip().split())
    return clean or fallback


def _social_channel(event_type: str, payload: dict[str, object]) -> Channel:
    platform = payload.get("platform")
    if platform in {"linkedin", "x"}:
        return platform  # type: ignore[return-value]
    platforms = payload.get("platforms")
    if platforms == ["linkedin"]:
        return "linkedin"
    if platforms == ["x"]:
        return "x"
    if event_type.startswith("variant_linkedin"):
        return "linkedin"
    return "social"


def _social_kind(event_type: str) -> InteractionKind:
    if "publish" in event_type or "published" in event_type:
        return "outbound"
    if event_type in {
        "variant_approved",
        "variant_rejected",
        "variant_archived",
        "variant_scheduled",
    }:
        return "approval"
    return "draft"


def _social_metadata(payload: dict[str, object]) -> dict[str, object]:
    allowed = {
        "content_hash",
        "draft_kind",
        "engagement_item_id",
        "error_type",
        "feedback_provided",
        "from_publish_status",
        "from_status",
        "linkedin_status_code",
        "platform",
        "platforms",
        "profile_version",
        "provider_comment_urn",
        "provider_post_urn",
        "publish_target",
        "review_friction",
        "review_edit_distance",
        "review_edit_ratio",
        "reviewed_content_hash",
        "reviewed_text_provided",
        "scheduled_for",
        "spark_memory_proposal_candidate",
        "spark_input",
        "trigger",
    }
    metadata = {key: value for key, value in payload.items() if key in allowed}
    spark_input = metadata.get("spark_input")
    if isinstance(spark_input, dict):
        metadata["spark_input"] = {
            "context_hash": spark_input.get("context_hash"),
            "context_available": spark_input.get("context_available"),
        }
    return metadata
