from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


SocialPlatform = Literal["x", "linkedin"]
SocialDraftStatus = Literal["needs_review", "approved", "rejected", "archived"]
SocialDraftKind = Literal["post", "reply"]
SocialPublishStatus = Literal["not_scheduled", "scheduled", "manual_published"]


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


class HeraldSocialDraftStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["approved", "rejected", "archived"]
    reviewer_notes: str | None = Field(default=None, max_length=500)


class HeraldSocialDraftScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_for: date


class HeraldSocialManualPublishUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    published_url: str = Field(min_length=8, max_length=500)


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
