from __future__ import annotations

import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from brain.db.pool import get_pool
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.models.herald_social import (
    HeraldSocialDraftCreate,
    HeraldSocialDraftCreateResponse,
    HeraldSocialDraftList,
    HeraldSocialDraftStatusUpdate,
    HeraldSocialDraftVariantOut,
    HeraldSocialPlatformProfileList,
    HeraldSocialPlatformProfileOut,
)
from brain.services.herald_social import create_social_draft, normalize_platforms

router = APIRouter(prefix="/v1/herald/social", tags=["herald-social"])


def _check_read_scope(request: Request) -> None:
    check_scopes(request, "herald.read", "at0_mail.read")


def _check_write_scope(request: Request) -> None:
    check_scopes(request, "herald.write", "at0_mail.write")


def _actor_sub(request: Request) -> str:
    return str(
        getattr(request.state, "user_sub", None)
        or getattr(request.state, "sub", None)
        or getattr(request.state, "user_id", None)
        or "unknown"
    )


def _actor_type(request: Request) -> str:
    return str(getattr(request.state, "actor_type", None) or "unknown")


@router.get("/platforms", response_model=HeraldSocialPlatformProfileList)
async def list_social_platform_profiles(
    request: Request,
    _: str = Depends(require_auth),
) -> HeraldSocialPlatformProfileList:
    _check_read_scope(request)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT platform, display_name, account_label, audience_notes,
                   voice_rules, safety_rules, max_chars, profile_version, active
            FROM public.alpha_herald_social_platform_profiles
            WHERE active = true
            ORDER BY platform
            """
        )
    return HeraldSocialPlatformProfileList(
        platforms=[HeraldSocialPlatformProfileOut(**dict(row)) for row in rows]
    )


@router.get("/drafts", response_model=HeraldSocialDraftList)
async def list_social_drafts(
    request: Request,
    _: str = Depends(require_auth),
    status: Literal[
        "needs_review",
        "approved",
        "rejected",
        "archived",
        "all",
    ] = Query(default="needs_review"),
    platform: Literal["x", "linkedin", "all"] = Query(default="all"),
    limit: int = Query(default=50, ge=1, le=200),
) -> HeraldSocialDraftList:
    _check_read_scope(request)
    filters: list[str] = []
    params: list[object] = []
    if status != "all":
        params.append(status)
        filters.append(f"v.status = ${len(params)}")
    if platform != "all":
        params.append(platform)
        filters.append(f"v.platform = ${len(params)}")
    where = " AND ".join(filters) if filters else "TRUE"
    params.append(limit)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT v.id, v.request_id, r.topic, r.source_url, r.campaign,
                   v.platform, v.account_label, v.draft_text, v.status,
                   v.variant_version, v.profile_version, v.audience_notes,
                   v.voice_rules, v.safety_rules, v.voice_score::float AS voice_score,
                   v.safety_flags, v.repeat_of_variant_id, v.reviewer_notes,
                   v.reviewed_by, v.reviewed_at, v.created_at
            FROM public.alpha_herald_social_draft_variants v
            JOIN public.alpha_herald_social_draft_requests r
              ON r.id = v.request_id
            WHERE {where}
            ORDER BY v.created_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return HeraldSocialDraftList(drafts=[_draft_out(row) for row in rows])


@router.post("/drafts", response_model=HeraldSocialDraftCreateResponse)
async def create_social_drafts(
    body: HeraldSocialDraftCreate,
    request: Request,
    _: str = Depends(require_auth),
) -> HeraldSocialDraftCreateResponse:
    _check_write_scope(request)
    try:
        platforms = normalize_platforms([str(platform) for platform in body.platforms])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    actor_sub = _actor_sub(request)
    actor_type = _actor_type(request)
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            profile_rows = await conn.fetch(
                """
                SELECT platform, display_name, account_label, audience_notes,
                       voice_rules, safety_rules, max_chars, profile_version
                FROM public.alpha_herald_social_platform_profiles
                WHERE active = true
                  AND platform = ANY($1::text[])
                """,
                list(platforms),
            )
            profiles = {row["platform"]: dict(row) for row in profile_rows}
            missing = [platform for platform in platforms if platform not in profiles]
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Social platform profile missing: {', '.join(missing)}",
                )

            request_id = await conn.fetchval(
                """
                INSERT INTO public.alpha_herald_social_draft_requests (
                    topic, source_url, campaign, account_label, requested_by
                )
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                body.topic.strip(),
                body.source_url.strip() if body.source_url else None,
                body.campaign.strip() if body.campaign else None,
                body.account_label.strip(),
                actor_sub,
            )
            await _record_event(
                conn,
                request_id=request_id,
                variant_id=None,
                event_type="request_created",
                actor_sub=actor_sub,
                actor_type=actor_type,
                payload={"platforms": list(platforms)},
            )

            draft_rows = []
            for platform in platforms:
                profile = profiles[platform]
                draft = create_social_draft(
                    topic=body.topic,
                    platform=platform,
                    max_chars=int(profile["max_chars"]),
                )
                repeat_of = await conn.fetchval(
                    """
                    SELECT id
                    FROM public.alpha_herald_social_draft_variants
                    WHERE platform = $1
                      AND content_hash = $2
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    platform,
                    draft.content_hash,
                )
                safety_flags = list(draft.safety_flags)
                if repeat_of is not None:
                    safety_flags.append("possible_repeat")
                row = await conn.fetchrow(
                    """
                    INSERT INTO public.alpha_herald_social_draft_variants (
                        request_id, platform, account_label, draft_text,
                        content_hash, profile_version, audience_notes,
                        voice_rules, safety_rules, voice_score, safety_flags,
                        repeat_of_variant_id
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, $7,
                        $8::text[], $9::text[], $10, $11::text[], $12
                    )
                    RETURNING id
                    """,
                    request_id,
                    platform,
                    body.account_label.strip(),
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
                variant_id = row["id"]
                await _record_event(
                    conn,
                    request_id=request_id,
                    variant_id=variant_id,
                    event_type="variant_created",
                    actor_sub=actor_sub,
                    actor_type=actor_type,
                    payload={
                        "platform": platform,
                        "profile_version": int(profile["profile_version"]),
                        "repeat": repeat_of is not None,
                    },
                )
                draft_rows.append(await _fetch_variant(conn, variant_id))

    return HeraldSocialDraftCreateResponse(
        request_id=request_id,
        drafts=[_draft_out(row) for row in draft_rows],
    )


@router.post("/drafts/{variant_id}/status", response_model=HeraldSocialDraftVariantOut)
async def update_social_draft_status(
    variant_id: UUID,
    body: HeraldSocialDraftStatusUpdate,
    request: Request,
    _: str = Depends(require_auth),
) -> HeraldSocialDraftVariantOut:
    _check_write_scope(request)
    actor_sub = _actor_sub(request)
    actor_type = _actor_type(request)
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow(
                """
                SELECT request_id, status
                FROM public.alpha_herald_social_draft_variants
                WHERE id = $1
                FOR UPDATE
                """,
                variant_id,
            )
            if current is None:
                raise HTTPException(status_code=404, detail="Social draft not found")

            await conn.execute(
                """
                UPDATE public.alpha_herald_social_draft_variants
                SET status = $2,
                    reviewer_notes = $3,
                    reviewed_by = $4,
                    reviewed_at = now(),
                    updated_at = now()
                WHERE id = $1
                """,
                variant_id,
                body.status,
                body.reviewer_notes,
                actor_sub,
            )
            await conn.execute(
                """
                UPDATE public.alpha_herald_social_draft_requests r
                SET status = CASE
                    WHEN EXISTS (
                        SELECT 1
                        FROM public.alpha_herald_social_draft_variants v
                        WHERE v.request_id = r.id
                          AND v.status = 'needs_review'
                    )
                    THEN 'drafted'
                    ELSE 'reviewed'
                END,
                updated_at = now()
                WHERE r.id = $1
                """,
                current["request_id"],
            )
            await _record_event(
                conn,
                request_id=current["request_id"],
                variant_id=variant_id,
                event_type=f"variant_{body.status}",
                actor_sub=actor_sub,
                actor_type=actor_type,
                payload={"from_status": current["status"]},
            )
            row = await _fetch_variant(conn, variant_id)
    return _draft_out(row)


async def _fetch_variant(conn, variant_id: UUID):
    row = await conn.fetchrow(
        """
        SELECT v.id, v.request_id, r.topic, r.source_url, r.campaign,
               v.platform, v.account_label, v.draft_text, v.status,
               v.variant_version, v.profile_version, v.audience_notes,
               v.voice_rules, v.safety_rules, v.voice_score::float AS voice_score,
               v.safety_flags, v.repeat_of_variant_id, v.reviewer_notes,
               v.reviewed_by, v.reviewed_at, v.created_at
        FROM public.alpha_herald_social_draft_variants v
        JOIN public.alpha_herald_social_draft_requests r
          ON r.id = v.request_id
        WHERE v.id = $1
        """,
        variant_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Social draft not found")
    return row


async def _record_event(
    conn,
    *,
    request_id,
    variant_id,
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


def _draft_out(row) -> HeraldSocialDraftVariantOut:
    return HeraldSocialDraftVariantOut(**dict(row))
