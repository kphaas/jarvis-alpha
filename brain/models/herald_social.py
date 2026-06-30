from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


SocialPlatform = Literal["x", "linkedin"]
SocialDraftStatus = Literal["needs_review", "approved", "rejected", "archived"]
SocialDraftKind = Literal["post", "reply"]
SocialReplyStyle = Literal["strong_short", "practical", "warm"]
SocialReviewFriction = Literal["as_is", "light_edit", "heavy_rewrite"]
SocialEngagementStatus = Literal[
    "needs_reply",
    "draft_created",
    "ignored",
    "replied",
    "archived",
]
SocialPublishStatus = Literal[
    "not_scheduled",
    "scheduled",
    "manual_published",
    "sending",
    "linkedin_published",
    "publish_failed",
]


def _default_social_platforms() -> list[SocialPlatform]:
    return ["x", "linkedin"]


class HeraldSocialPlatformProfileOut(BaseModel):
    platform: SocialPlatform
    display_name: str
    account_label: str
    audience_notes: str
    voice_rules: list[str]
    safety_rules: list[str]
    max_chars: int
    profile_version: int
    active: bool


class HeraldSocialPlatformProfileList(BaseModel):
    platforms: list[HeraldSocialPlatformProfileOut]


class HeraldSocialDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=3, max_length=500)
    platforms: list[SocialPlatform] = Field(default_factory=_default_social_platforms)
    account_label: str = Field(default="AT0", min_length=1, max_length=80)
    source_url: str | None = Field(default=None, min_length=8, max_length=500)
    campaign: str | None = Field(default=None, min_length=2, max_length=120)
    draft_kind: SocialDraftKind = "post"
    engagement_author: str | None = Field(default=None, min_length=1, max_length=120)
    reply_style: SocialReplyStyle | None = None
    reply_styles: list[SocialReplyStyle] = Field(default_factory=list, max_length=3)


class HeraldSocialDraftStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "rejected", "archived"]
    reviewer_notes: str | None = Field(default=None, max_length=500)
    review_friction: SocialReviewFriction | None = None


class HeraldSocialDraftScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_for: date


class HeraldSocialManualPublishUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    published_url: str = Field(min_length=8, max_length=500)


class HeraldLinkedInIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    post_urn: str = Field(min_length=8, max_length=200)
    limit: int = Field(default=25, ge=1, le=50)


class HeraldLinkedInIngestResponse(BaseModel):
    post_urn: str
    imported_count: int
    skipped_count: int


class HeraldLinkedInScoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topics: list[str] = Field(default_factory=list, max_length=8)
    per_topic: int = Field(default=2, ge=1, le=5)
    max_targets: int = Field(default=6, ge=1, le=12)


class HeraldLinkedInScoutResponse(BaseModel):
    created_count: int
    skipped_count: int
    reason: str
    item_ids: list[UUID]


class HeraldLinkedInMetricRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_id: UUID
    engagement_item_id: UUID | None = None
    metric_source: Literal["manual", "linkedin_api"] = "manual"
    impressions: int = Field(default=0, ge=0, le=2_147_483_647)
    reactions: int = Field(default=0, ge=0, le=2_147_483_647)
    comments: int = Field(default=0, ge=0, le=2_147_483_647)
    reposts: int = Field(default=0, ge=0, le=2_147_483_647)
    profile_clicks: int = Field(default=0, ge=0, le=2_147_483_647)
    captured_on: date | None = None
    notes: str | None = Field(default=None, max_length=500)


class HeraldLinkedInMetricOut(BaseModel):
    metric_id: UUID
    variant_id: UUID
    engagement_total: int
    engagement_rate: float
    spark_memory_saved: bool
    spark_memory_content: str | None = None


class HeraldLinkedInOperatorDashboardOut(BaseModel):
    post_due: bool
    comments_due: int
    best_topic: str
    best_reply_style: SocialReplyStyle
    targets_ready: int
    approval_backlog: int
    active_thought_leaders: int
    metric_snapshots_30d: int
    metrics_due_count: int
    learning_samples_30d: int
    metrics_learning_ready: bool
    review_friction_30d: dict[str, int]


class HeraldLinkedInAnalyticsDigestOut(BaseModel):
    week_of: date
    headline: str
    recommendations: list[str]
    best_topic: str
    best_reply_style: SocialReplyStyle
    metrics_due_count: int
    metric_snapshots_30d: int
    metrics_learning_ready: bool


class HeraldThoughtLeaderTargetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_name: str = Field(min_length=1, max_length=160)
    company_name: str | None = Field(default=None, max_length=160)
    role_title: str | None = Field(default=None, max_length=160)
    profile_url: str | None = Field(default=None, min_length=8, max_length=500)
    topics: list[str] = Field(default_factory=list, max_length=8)
    priority: int = Field(default=3, ge=1, le=5)
    relationship_notes: str | None = Field(default=None, max_length=1000)


class HeraldThoughtLeaderTargetOut(BaseModel):
    id: UUID
    platform: Literal["linkedin"]
    person_name: str
    company_name: str | None
    role_title: str | None
    profile_url: str | None
    topics: list[str]
    priority: int
    relationship_notes: str | None
    last_interaction_at: datetime | None
    status: Literal["active", "paused", "archived"]
    created_at: datetime
    updated_at: datetime


class HeraldThoughtLeaderTargetList(BaseModel):
    targets: list[HeraldThoughtLeaderTargetOut]


class HeraldSocialEngagementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_text: str = Field(min_length=3, max_length=1200)
    author_name: str = Field(min_length=1, max_length=160)
    item_url: str | None = Field(default=None, min_length=8, max_length=500)
    provider_item_urn: str | None = Field(default=None, min_length=8, max_length=200)
    provider_post_urn: str | None = Field(default=None, min_length=8, max_length=200)
    account_label: str = Field(default="AT0", min_length=1, max_length=80)
    source: Literal["manual", "linkedin_api"] = "manual"


class HeraldSocialEngagementStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ignored", "replied", "archived"]


class HeraldSocialDraftVariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    request_id: UUID
    topic: str
    source_url: str | None
    campaign: str | None
    draft_kind: SocialDraftKind
    engagement_author: str | None
    platform: SocialPlatform
    account_label: str
    draft_text: str
    status: SocialDraftStatus
    publish_status: SocialPublishStatus
    scheduled_for: date | None
    published_at: datetime | None
    published_url: str | None
    publish_attempt_count: int
    last_publish_attempt_at: datetime | None
    publish_error_type: str | None
    publish_error_message: str | None
    provider_post_urn: str | None
    variant_version: int
    profile_version: int
    audience_notes: str
    voice_rules: list[str]
    safety_rules: list[str]
    voice_score: float
    safety_flags: list[str]
    repeat_of_variant_id: UUID | None
    reviewer_notes: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime


class HeraldSocialDraftList(BaseModel):
    drafts: list[HeraldSocialDraftVariantOut]


class HeraldSocialDraftCreateResponse(BaseModel):
    request_id: UUID
    drafts: list[HeraldSocialDraftVariantOut]


class HeraldLinkedInCadenceOut(BaseModel):
    today: date
    next_due_date: date
    last_published_at: datetime | None
    next_scheduled_for: date | None
    approved_ready_count: int


class HeraldLinkedInReadPlanOut(BaseModel):
    status: Literal["planned_pending_linkedin_approval"]
    write_scope: str
    required_read_scopes: list[str]
    discovery_targets: list[str]
    boundary: list[str]


class HeraldSocialEngagementOut(BaseModel):
    id: UUID
    platform: Literal["linkedin"]
    source: Literal["manual", "linkedin_api"]
    account_label: str
    provider_item_urn: str | None
    provider_post_urn: str | None
    item_url: str | None
    author_name: str
    item_text: str
    status: SocialEngagementStatus
    reply_variant_id: UUID | None
    discovered_at: datetime
    created_at: datetime
    updated_at: datetime


class HeraldSocialEngagementList(BaseModel):
    items: list[HeraldSocialEngagementOut]
