from __future__ import annotations

import json
from datetime import timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from brain.db.pool import get_pool
from brain.middleware.jwt_auth import require_auth
from brain.middleware.scopes import check_scopes
from brain.models.herald_social import (
    HeraldLinkedInCadenceOut,
    HeraldLinkedInIngestRequest,
    HeraldLinkedInIngestResponse,
    HeraldLinkedInScoutRequest,
    HeraldLinkedInScoutResponse,
    HeraldLinkedInReadPlanOut,
    HeraldSocialDraftCreate,
    HeraldSocialDraftCreateResponse,
    HeraldSocialDraftList,
    HeraldSocialDraftScheduleUpdate,
    HeraldSocialDraftStatusUpdate,
    HeraldSocialDraftVariantOut,
    HeraldSocialEngagementCreate,
    HeraldSocialEngagementList,
    HeraldSocialEngagementOut,
    HeraldSocialEngagementStatusUpdate,
    HeraldSocialManualPublishUpdate,
    HeraldSocialPlatformProfileList,
    HeraldSocialPlatformProfileOut,
    SocialReplyStyle,
)
from brain.services.herald_linkedin import (
    HeraldLinkedInConfigError,
    HeraldLinkedInIngestDisabled,
    HeraldLinkedInPublishError,
    fetch_linkedin_comments,
    publish_linkedin_comment,
    publish_linkedin_text,
)
from brain.services.herald_social import (
    create_social_draft,
    linkedin_engagement_reply_topic,
    linkedin_weekly_topic,
    load_herald_spark_context,
    normalize_platforms,
    scout_linkedin_engagement_targets,
)
from brain.services.internet_scout.gateway_client import InternetScoutGatewayError

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
                   r.draft_kind, r.engagement_author,
                   v.platform, v.account_label, v.draft_text, v.status,
                   v.publish_status, v.scheduled_for, v.published_at, v.published_url,
                   v.publish_attempt_count, v.last_publish_attempt_at,
                   v.publish_error_type, v.publish_error_message, v.provider_post_urn,
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
    return await _create_social_drafts(body=body, request=request)


@router.get("/linkedin/cadence", response_model=HeraldLinkedInCadenceOut)
async def get_linkedin_cadence(
    request: Request,
    _: str = Depends(require_auth),
) -> HeraldLinkedInCadenceOut:
    _check_read_scope(request)
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT current_date AS today,
                   max(v.published_at) FILTER (
                       WHERE v.platform = 'linkedin'
                         AND v.publish_status IN (
                             'manual_published', 'linkedin_published'
                         )
                   ) AS last_published_at,
                   min(v.scheduled_for) FILTER (
                       WHERE v.platform = 'linkedin'
                         AND v.publish_status = 'scheduled'
                         AND v.scheduled_for >= current_date
                   ) AS next_scheduled_for,
                   count(*) FILTER (
                       WHERE v.platform = 'linkedin'
                         AND v.status = 'approved'
                         AND v.publish_status IN ('not_scheduled', 'scheduled')
                   )::int AS approved_ready_count
            FROM public.alpha_herald_social_draft_variants v
            """
        )
    today = row["today"]
    last_published_at = row["last_published_at"]
    next_due_date = (
        last_published_at.date() + timedelta(days=7)
        if last_published_at is not None
        else today
    )
    return HeraldLinkedInCadenceOut(
        today=today,
        next_due_date=next_due_date,
        last_published_at=last_published_at,
        next_scheduled_for=row["next_scheduled_for"],
        approved_ready_count=int(row["approved_ready_count"] or 0),
    )


@router.get("/linkedin/read-plan", response_model=HeraldLinkedInReadPlanOut)
async def get_linkedin_read_plan(
    request: Request,
    _: str = Depends(require_auth),
) -> HeraldLinkedInReadPlanOut:
    _check_read_scope(request)
    return HeraldLinkedInReadPlanOut(
        status="planned_pending_linkedin_approval",
        write_scope="w_member_social_feed",
        required_read_scopes=["r_member_social_feed"],
        discovery_targets=[
            "comments on AT0 member posts",
            "reactions and mentions on owned LinkedIn activity",
            "public AI and business-transformation targets from Gateway search",
            "public URLs Ken adds manually until read access is approved",
        ],
        boundary=[
            "no autonomous likes, follows, DMs, comments, or reposts",
            "read connector inserts needs_reply items only",
            "reply drafts require human approval before publish",
        ],
    )


@router.get("/linkedin/engagements", response_model=HeraldSocialEngagementList)
async def list_linkedin_engagements(
    request: Request,
    _: str = Depends(require_auth),
    status: Literal[
        "needs_reply",
        "draft_created",
        "ignored",
        "replied",
        "archived",
        "all",
    ] = Query(default="needs_reply"),
    limit: int = Query(default=50, ge=1, le=200),
) -> HeraldSocialEngagementList:
    _check_read_scope(request)
    params: list[object] = []
    where = "TRUE"
    if status != "all":
        params.append(status)
        where = f"status = ${len(params)}"
    params.append(limit)
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT id, platform, source, account_label, provider_item_urn,
                   provider_post_urn, item_url, author_name, item_text, status,
                   reply_variant_id, discovered_at, created_at, updated_at
            FROM public.alpha_herald_social_engagement_items
            WHERE {where}
            ORDER BY discovered_at DESC
            LIMIT ${len(params)}
            """,
            *params,
        )
    return HeraldSocialEngagementList(items=[_engagement_out(row) for row in rows])


@router.post("/linkedin/engagements", response_model=HeraldSocialEngagementOut)
async def create_linkedin_engagement(
    body: HeraldSocialEngagementCreate,
    request: Request,
    _: str = Depends(require_auth),
) -> HeraldSocialEngagementOut:
    _check_write_scope(request)
    actor_sub = _actor_sub(request)
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO public.alpha_herald_social_engagement_items (
                source, account_label, provider_item_urn, provider_post_urn,
                item_url, author_name, item_text, created_by
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (provider_item_urn) WHERE provider_item_urn IS NOT NULL
            DO UPDATE SET
                item_url = EXCLUDED.item_url,
                author_name = EXCLUDED.author_name,
                item_text = EXCLUDED.item_text,
                updated_at = now()
            RETURNING id, platform, source, account_label, provider_item_urn,
                      provider_post_urn, item_url, author_name, item_text, status,
                      reply_variant_id, discovered_at, created_at, updated_at
            """,
            body.source,
            body.account_label.strip(),
            body.provider_item_urn.strip() if body.provider_item_urn else None,
            body.provider_post_urn.strip() if body.provider_post_urn else None,
            body.item_url.strip() if body.item_url else None,
            body.author_name.strip(),
            body.item_text.strip(),
            actor_sub,
        )
    return _engagement_out(row)


@router.post("/linkedin/ingest", response_model=HeraldLinkedInIngestResponse)
async def ingest_linkedin_comments(
    body: HeraldLinkedInIngestRequest,
    request: Request,
    _: str = Depends(require_auth),
) -> HeraldLinkedInIngestResponse:
    _check_write_scope(request)
    actor_sub = _actor_sub(request)
    try:
        comments = await fetch_linkedin_comments(
            post_urn=body.post_urn,
            limit=body.limit,
        )
    except HeraldLinkedInIngestDisabled as exc:
        raise HTTPException(status_code=409, detail="linkedin_ingest_disabled") from exc
    except (HeraldLinkedInConfigError, HeraldLinkedInPublishError) as exc:
        raise HTTPException(status_code=502, detail="linkedin_ingest_failed") from exc

    imported = 0
    skipped = 0
    async with get_pool().acquire() as conn:
        for comment in comments:
            if not comment.item_text.strip():
                skipped += 1
                continue
            status = await conn.fetchval(
                """
                INSERT INTO public.alpha_herald_social_engagement_items (
                    source, account_label, provider_item_urn, provider_post_urn,
                    item_url, author_name, item_text, created_by
                )
                VALUES (
                    'linkedin_api', 'AT0', $1, $2, $3, $4, $5, $6
                )
                ON CONFLICT (provider_item_urn) WHERE provider_item_urn IS NOT NULL
                DO UPDATE SET
                    item_url = EXCLUDED.item_url,
                    author_name = EXCLUDED.author_name,
                    item_text = EXCLUDED.item_text,
                    updated_at = now()
                RETURNING xmax = 0
                """,
                comment.provider_item_urn,
                comment.provider_post_urn,
                comment.item_url,
                comment.author_name,
                comment.item_text,
                actor_sub,
            )
            imported += 1 if status else 0
            skipped += 0 if status else 1
    return HeraldLinkedInIngestResponse(
        post_urn=body.post_urn.strip(),
        imported_count=imported,
        skipped_count=skipped,
    )


@router.post("/linkedin/engagements/scout", response_model=HeraldLinkedInScoutResponse)
async def scout_linkedin_engagements(
    body: HeraldLinkedInScoutRequest,
    request: Request,
    _: str = Depends(require_auth),
) -> HeraldLinkedInScoutResponse:
    _check_write_scope(request)
    try:
        async with get_pool().acquire() as conn:
            outcome = await scout_linkedin_engagement_targets(
                conn,
                actor_sub=_actor_sub(request),
                topics=body.topics or None,
                per_topic=body.per_topic,
                max_targets=body.max_targets,
            )
    except InternetScoutGatewayError as exc:
        raise HTTPException(status_code=502, detail="linkedin_scout_failed") from exc
    return HeraldLinkedInScoutResponse(
        created_count=outcome.created_count,
        skipped_count=outcome.skipped_count,
        reason=outcome.reason,
        item_ids=list(outcome.item_ids),
    )


@router.post(
    "/linkedin/engagements/{item_id}/draft-reply",
    response_model=HeraldSocialDraftCreateResponse,
)
async def draft_linkedin_engagement_reply(
    item_id: UUID,
    request: Request,
    _: str = Depends(require_auth),
) -> HeraldSocialDraftCreateResponse:
    _check_write_scope(request)
    async with get_pool().acquire() as conn:
        item = await conn.fetchrow(
            """
            SELECT id, author_name, item_text, item_url, status
            FROM public.alpha_herald_social_engagement_items
            WHERE id = $1
            """,
            item_id,
        )
    if item is None:
        raise HTTPException(status_code=404, detail="LinkedIn engagement not found")
    if item["status"] in {"ignored", "archived"}:
        raise HTTPException(status_code=409, detail="engagement_closed")

    body = HeraldSocialDraftCreate(
        topic=linkedin_engagement_reply_topic(str(item["item_text"])),
        platforms=["linkedin"],
        account_label="AT0",
        source_url=item["item_url"],
        campaign="linkedin-engagement-inbox",
        draft_kind="reply",
        engagement_author=str(item["author_name"]),
        reply_styles=["strong_short", "practical", "warm"],
    )
    response = await _create_social_drafts(body=body, request=request)
    variant_id = response.drafts[0].id if response.drafts else None
    if variant_id is not None:
        async with get_pool().acquire() as conn:
            await conn.execute(
                """
                UPDATE public.alpha_herald_social_engagement_items
                SET status = 'draft_created',
                    reply_variant_id = $2,
                    updated_at = now()
                WHERE id = $1
                """,
                item_id,
                variant_id,
            )
    return response


@router.post(
    "/linkedin/engagements/{item_id}/publish-reply",
    response_model=HeraldSocialDraftVariantOut,
)
async def publish_linkedin_engagement_reply(
    item_id: UUID,
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
                SELECT e.id, e.status AS engagement_status, e.provider_post_urn,
                       e.reply_variant_id, v.request_id, v.platform, v.status,
                       v.publish_status, v.draft_text, v.content_hash,
                       r.draft_kind
                FROM public.alpha_herald_social_engagement_items e
                JOIN public.alpha_herald_social_draft_variants v
                  ON v.id = e.reply_variant_id
                JOIN public.alpha_herald_social_draft_requests r
                  ON r.id = v.request_id
                WHERE e.id = $1
                FOR UPDATE
                """,
                item_id,
            )
            if current is None:
                raise HTTPException(status_code=404, detail="LinkedIn reply not found")
            if current["provider_post_urn"] is None:
                raise HTTPException(status_code=409, detail="linkedin_post_urn_missing")
            if current["draft_kind"] != "reply":
                raise HTTPException(status_code=400, detail="reply_draft_required")
            if current["platform"] != "linkedin":
                raise HTTPException(status_code=400, detail="linkedin_only")
            if current["status"] != "approved":
                raise HTTPException(status_code=409, detail="draft_not_approved")
            if current["engagement_status"] == "replied":
                raise HTTPException(
                    status_code=409, detail="engagement_already_replied"
                )
            if current["publish_status"] in {"manual_published", "linkedin_published"}:
                raise HTTPException(status_code=409, detail="draft_already_published")
            if current["publish_status"] == "sending":
                raise HTTPException(status_code=409, detail="draft_publish_in_progress")

            await conn.execute(
                """
                UPDATE public.alpha_herald_social_draft_variants
                SET publish_status = 'sending',
                    publish_attempt_count = publish_attempt_count + 1,
                    last_publish_attempt_at = now(),
                    publish_error_type = NULL,
                    publish_error_message = NULL,
                    updated_at = now()
                WHERE id = $1
                """,
                current["reply_variant_id"],
            )
            await _record_event(
                conn,
                request_id=current["request_id"],
                variant_id=current["reply_variant_id"],
                event_type="variant_linkedin_publish_started",
                actor_sub=actor_sub,
                actor_type=actor_type,
                payload={
                    "publish_target": "comment",
                    "content_hash": current["content_hash"],
                },
            )
            post_urn = str(current["provider_post_urn"])
            draft_text = str(current["draft_text"])
            variant_id = current["reply_variant_id"]
            request_id = current["request_id"]

    try:
        result = await publish_linkedin_comment(post_urn=post_urn, text=draft_text)
    except (HeraldLinkedInConfigError, HeraldLinkedInPublishError) as exc:
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                await _record_linkedin_publish_failure(
                    conn,
                    variant_id=variant_id,
                    request_id=request_id,
                    actor_sub=actor_sub,
                    actor_type=actor_type,
                    exc=exc,
                )
        raise HTTPException(status_code=502, detail="linkedin_comment_failed") from exc

    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE public.alpha_herald_social_draft_variants
                SET publish_status = 'linkedin_published',
                    published_at = now(),
                    published_url = $2,
                    provider_post_urn = $3,
                    publish_error_type = NULL,
                    publish_error_message = NULL,
                    updated_at = now()
                WHERE id = $1
                """,
                variant_id,
                result.published_url,
                post_urn,
            )
            await conn.execute(
                """
                UPDATE public.alpha_herald_social_engagement_items
                SET status = 'replied',
                    updated_at = now()
                WHERE id = $1
                """,
                item_id,
            )
            await _record_event(
                conn,
                request_id=request_id,
                variant_id=variant_id,
                event_type="variant_linkedin_published",
                actor_sub=actor_sub,
                actor_type=actor_type,
                payload={
                    "publish_target": "comment",
                    "linkedin_status_code": result.status_code,
                    "provider_comment_urn": result.provider_post_urn,
                },
            )
            row = await _fetch_variant(conn, variant_id)
    return _draft_out(row)


@router.post(
    "/linkedin/engagements/{item_id}/status",
    response_model=HeraldSocialEngagementOut,
)
async def update_linkedin_engagement_status(
    item_id: UUID,
    body: HeraldSocialEngagementStatusUpdate,
    request: Request,
    _: str = Depends(require_auth),
) -> HeraldSocialEngagementOut:
    _check_write_scope(request)
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE public.alpha_herald_social_engagement_items
            SET status = $2,
                updated_at = now()
            WHERE id = $1
            RETURNING id, platform, source, account_label, provider_item_urn,
                      provider_post_urn, item_url, author_name, item_text, status,
                      reply_variant_id, discovered_at, created_at, updated_at
            """,
            item_id,
            body.status,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="LinkedIn engagement not found")
    return _engagement_out(row)


@router.post("/linkedin/weekly", response_model=HeraldSocialDraftCreateResponse)
async def create_linkedin_weekly_draft(
    request: Request,
    _: str = Depends(require_auth),
) -> HeraldSocialDraftCreateResponse:
    _check_write_scope(request)
    async with get_pool().acquire() as conn:
        today = await conn.fetchval("SELECT current_date")
    body = HeraldSocialDraftCreate(
        topic=linkedin_weekly_topic(today),
        platforms=["linkedin"],
        account_label="AT0",
        campaign="linkedin-weekly-brand",
    )
    return await _create_social_drafts(body=body, request=request)


async def _create_social_drafts(
    *,
    body: HeraldSocialDraftCreate,
    request: Request,
) -> HeraldSocialDraftCreateResponse:
    _check_write_scope(request)
    try:
        platforms = normalize_platforms([str(platform) for platform in body.platforms])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if body.draft_kind == "reply" and platforms != ("linkedin",):
        raise HTTPException(status_code=400, detail="reply_drafts_linkedin_only")

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
            spark_context, spark_meta = await load_herald_spark_context(conn)

            request_id = await conn.fetchval(
                """
                INSERT INTO public.alpha_herald_social_draft_requests (
                    topic, source_url, campaign, account_label, requested_by,
                    draft_kind, engagement_author
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                body.topic.strip(),
                body.source_url.strip() if body.source_url else None,
                body.campaign.strip() if body.campaign else None,
                body.account_label.strip(),
                actor_sub,
                body.draft_kind,
                body.engagement_author.strip() if body.engagement_author else None,
            )
            await _record_event(
                conn,
                request_id=request_id,
                variant_id=None,
                event_type="request_created",
                actor_sub=actor_sub,
                actor_type=actor_type,
                payload={
                    "draft_kind": body.draft_kind,
                    "platforms": list(platforms),
                    "spark_input": {
                        "topic": body.topic.strip(),
                        "context_hash": spark_meta.get("context_hash"),
                        "context_available": spark_meta.get("context_available"),
                    },
                },
            )

            draft_rows = []
            reply_styles = _reply_styles_for(body)
            for platform in platforms:
                profile = profiles[platform]
                for reply_style in reply_styles:
                    draft = create_social_draft(
                        topic=body.topic,
                        platform=platform,
                        max_chars=int(profile["max_chars"]),
                        draft_kind=body.draft_kind,
                        engagement_author=body.engagement_author,
                        reply_style=reply_style,
                        spark_context=spark_context,
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
                            "draft_kind": body.draft_kind,
                            "reply_style": reply_style
                            if body.draft_kind == "reply"
                            else None,
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
                SELECT v.request_id, v.status, r.draft_kind
                FROM public.alpha_herald_social_draft_variants v
                JOIN public.alpha_herald_social_draft_requests r
                  ON r.id = v.request_id
                WHERE v.id = $1
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
            if body.status == "approved" and current["draft_kind"] == "reply":
                await conn.execute(
                    """
                    UPDATE public.alpha_herald_social_engagement_items e
                    SET reply_variant_id = $1,
                        updated_at = now()
                    WHERE e.reply_variant_id IN (
                        SELECT v.id
                        FROM public.alpha_herald_social_draft_variants v
                        WHERE v.request_id = $2
                    )
                    """,
                    variant_id,
                    current["request_id"],
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
                payload={
                    "from_status": current["status"],
                    "feedback_provided": bool(body.reviewer_notes),
                },
            )
            row = await _fetch_variant(conn, variant_id)
    return _draft_out(row)


def _reply_styles_for(body: HeraldSocialDraftCreate) -> tuple[SocialReplyStyle, ...]:
    if body.draft_kind != "reply":
        return ("practical",)
    styles = body.reply_styles or ([body.reply_style] if body.reply_style else [])
    if not styles:
        styles = ["practical"]
    return tuple(dict.fromkeys(styles))


@router.post(
    "/drafts/{variant_id}/publish/linkedin",
    response_model=HeraldSocialDraftVariantOut,
)
async def publish_linkedin_draft(
    variant_id: UUID,
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
                SELECT request_id, platform, status, publish_status, draft_text,
                       content_hash
                FROM public.alpha_herald_social_draft_variants
                WHERE id = $1
                FOR UPDATE
                """,
                variant_id,
            )
            if current is None:
                raise HTTPException(status_code=404, detail="Social draft not found")
            if current["platform"] != "linkedin":
                raise HTTPException(status_code=400, detail="linkedin_only")
            if current["status"] != "approved":
                raise HTTPException(status_code=409, detail="draft_not_approved")
            if current["publish_status"] in {"manual_published", "linkedin_published"}:
                raise HTTPException(status_code=409, detail="draft_already_published")
            if current["publish_status"] == "sending":
                raise HTTPException(status_code=409, detail="draft_publish_in_progress")

            await conn.execute(
                """
                UPDATE public.alpha_herald_social_draft_variants
                SET publish_status = 'sending',
                    publish_attempt_count = publish_attempt_count + 1,
                    last_publish_attempt_at = now(),
                    publish_error_type = NULL,
                    publish_error_message = NULL,
                    updated_at = now()
                WHERE id = $1
                """,
                variant_id,
            )
            await _record_event(
                conn,
                request_id=current["request_id"],
                variant_id=variant_id,
                event_type="variant_linkedin_publish_started",
                actor_sub=actor_sub,
                actor_type=actor_type,
                payload={"content_hash": current["content_hash"]},
            )
            draft_text = str(current["draft_text"])

    try:
        result = await publish_linkedin_text(draft_text)
    except (HeraldLinkedInConfigError, HeraldLinkedInPublishError) as exc:
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                await _record_linkedin_publish_failure(
                    conn,
                    variant_id=variant_id,
                    request_id=current["request_id"],
                    actor_sub=actor_sub,
                    actor_type=actor_type,
                    exc=exc,
                )
        raise HTTPException(status_code=502, detail="linkedin_publish_failed") from exc

    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE public.alpha_herald_social_draft_variants
                SET publish_status = 'linkedin_published',
                    published_at = now(),
                    published_url = $2,
                    provider_post_urn = $3,
                    publish_error_type = NULL,
                    publish_error_message = NULL,
                    updated_at = now()
                WHERE id = $1
                """,
                variant_id,
                result.published_url,
                result.provider_post_urn,
            )
            await _record_event(
                conn,
                request_id=current["request_id"],
                variant_id=variant_id,
                event_type="variant_linkedin_published",
                actor_sub=actor_sub,
                actor_type=actor_type,
                payload={
                    "linkedin_status_code": result.status_code,
                    "provider_post_urn": result.provider_post_urn,
                },
            )
            row = await _fetch_variant(conn, variant_id)
    return _draft_out(row)


@router.post(
    "/drafts/{variant_id}/schedule", response_model=HeraldSocialDraftVariantOut
)
async def schedule_linkedin_draft(
    variant_id: UUID,
    body: HeraldSocialDraftScheduleUpdate,
    request: Request,
    _: str = Depends(require_auth),
) -> HeraldSocialDraftVariantOut:
    _check_write_scope(request)
    actor_sub = _actor_sub(request)
    actor_type = _actor_type(request)
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            today = await conn.fetchval("SELECT current_date")
            if body.scheduled_for < today:
                raise HTTPException(status_code=400, detail="scheduled_for_past")
            current = await conn.fetchrow(
                """
                SELECT request_id, platform, status
                FROM public.alpha_herald_social_draft_variants
                WHERE id = $1
                FOR UPDATE
                """,
                variant_id,
            )
            if current is None:
                raise HTTPException(status_code=404, detail="Social draft not found")
            if current["platform"] != "linkedin":
                raise HTTPException(status_code=400, detail="linkedin_only")
            if current["status"] != "approved":
                raise HTTPException(status_code=409, detail="draft_not_approved")

            await conn.execute(
                """
                UPDATE public.alpha_herald_social_draft_variants
                SET scheduled_for = $2,
                    publish_status = 'scheduled',
                    updated_at = now()
                WHERE id = $1
                """,
                variant_id,
                body.scheduled_for,
            )
            await _record_event(
                conn,
                request_id=current["request_id"],
                variant_id=variant_id,
                event_type="variant_scheduled",
                actor_sub=actor_sub,
                actor_type=actor_type,
                payload={"scheduled_for": body.scheduled_for.isoformat()},
            )
            row = await _fetch_variant(conn, variant_id)
    return _draft_out(row)


@router.post(
    "/drafts/{variant_id}/publish/manual",
    response_model=HeraldSocialDraftVariantOut,
)
async def mark_linkedin_draft_manually_published(
    variant_id: UUID,
    body: HeraldSocialManualPublishUpdate,
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
                SELECT request_id, platform, status, publish_status
                FROM public.alpha_herald_social_draft_variants
                WHERE id = $1
                FOR UPDATE
                """,
                variant_id,
            )
            if current is None:
                raise HTTPException(status_code=404, detail="Social draft not found")
            if current["platform"] != "linkedin":
                raise HTTPException(status_code=400, detail="linkedin_only")
            if current["status"] != "approved":
                raise HTTPException(status_code=409, detail="draft_not_approved")

            await conn.execute(
                """
                UPDATE public.alpha_herald_social_draft_variants
                SET publish_status = 'manual_published',
                    published_at = now(),
                    published_url = $2,
                    updated_at = now()
                WHERE id = $1
                """,
                variant_id,
                body.published_url.strip(),
            )
            await _record_event(
                conn,
                request_id=current["request_id"],
                variant_id=variant_id,
                event_type="variant_manual_published",
                actor_sub=actor_sub,
                actor_type=actor_type,
                payload={
                    "from_publish_status": current["publish_status"],
                    "published_url": body.published_url.strip(),
                },
            )
            row = await _fetch_variant(conn, variant_id)
    return _draft_out(row)


async def _fetch_variant(conn, variant_id: UUID):
    row = await conn.fetchrow(
        """
        SELECT v.id, v.request_id, r.topic, r.source_url, r.campaign,
               r.draft_kind, r.engagement_author,
               v.platform, v.account_label, v.draft_text, v.status,
               v.publish_status, v.scheduled_for, v.published_at, v.published_url,
               v.publish_attempt_count, v.last_publish_attempt_at,
               v.publish_error_type, v.publish_error_message, v.provider_post_urn,
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


async def _record_linkedin_publish_failure(
    conn,
    *,
    variant_id: UUID,
    request_id,
    actor_sub: str,
    actor_type: str,
    exc: Exception,
) -> None:
    error_type = exc.__class__.__name__
    await conn.execute(
        """
        UPDATE public.alpha_herald_social_draft_variants
        SET publish_status = 'publish_failed',
            publish_error_type = $2,
            publish_error_message = 'linkedin_publish_failed',
            updated_at = now()
        WHERE id = $1
        """,
        variant_id,
        error_type,
    )
    await _record_event(
        conn,
        request_id=request_id,
        variant_id=variant_id,
        event_type="variant_linkedin_publish_failed",
        actor_sub=actor_sub,
        actor_type=actor_type,
        payload={"error_type": error_type},
    )


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


def _engagement_out(row) -> HeraldSocialEngagementOut:
    return HeraldSocialEngagementOut(**dict(row))
