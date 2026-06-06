"""Typed contracts for Beacon internet-scout planning and evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ApprovalTier = Literal["T1", "T2", "T3", "T4", "T5"]
Sensitivity = Literal["normal", "privacy", "legal", "financial", "minor"]


class InternetTool(str, Enum):
    SEARCH = "search"
    FETCH = "fetch"
    EXTRACT = "extract"
    CRAWL = "crawl"
    BROWSER_USE = "browser_use"


class InternetScoutRequest(BaseModel):
    """Operator or system request for read-only public internet evidence."""

    query: str | None = Field(default=None, max_length=2000)
    urls: list[str] = Field(default_factory=list, max_length=20)
    tool_hint: InternetTool | None = None
    max_pages: int = Field(default=1, ge=1, le=50)
    max_depth: int = Field(default=0, ge=0, le=5)
    needs_interaction: bool = False
    sensitivity: Sensitivity = "normal"
    requester: str = Field(default="alpha", min_length=1, max_length=96)

    @field_validator("query")
    @classmethod
    def _blank_query_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("urls")
    @classmethod
    def _strip_urls(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]


class UrlSafetyResult(BaseModel):
    original_url: str
    normalized_url: str | None = None
    host: str | None = None
    allowed: bool
    reasons: list[str] = Field(default_factory=list)


class ContentSafetyResult(BaseModel):
    allowed: bool
    content_type: str | None = None
    content_length: int | None = None
    reasons: list[str] = Field(default_factory=list)


class SanitizedContent(BaseModel):
    text: str
    truncated: bool
    risk_markers: list[str] = Field(default_factory=list)
    trusted_instructions: bool = False


class PolicyDecision(BaseModel):
    tool: InternetTool
    allowed: bool
    requires_approval: bool
    tier: ApprovalTier
    reason: str
    blocked_reasons: list[str] = Field(default_factory=list)


class SourceReference(BaseModel):
    url: str
    host: str
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    title: str | None = Field(default=None, max_length=500)


class EvidenceClaim(BaseModel):
    claim: str = Field(min_length=1, max_length=2000)
    source_url: str
    citation_text: str = Field(min_length=1, max_length=1000)
    confidence: Literal["low", "medium", "high"] = "medium"


class InternetEvidencePacket(BaseModel):
    request: InternetScoutRequest
    sources: list[SourceReference] = Field(default_factory=list, max_length=50)
    claims: list[EvidenceClaim] = Field(default_factory=list, max_length=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InternetScoutPlan(BaseModel):
    request: InternetScoutRequest
    selected_tool: InternetTool
    decision: PolicyDecision
    execution_enabled: bool = False
    gateway_required: bool = True
    notes: list[str] = Field(default_factory=list)


class GatewaySearchResult(BaseModel):
    title: str | None = None
    url: str
    host: str
    description: str = ""
    risk_markers: list[str] = Field(default_factory=list)


class GatewaySearchResponse(BaseModel):
    provider: str
    query_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    fetched_at: datetime
    results: list[GatewaySearchResult] = Field(default_factory=list, max_length=10)


class GatewayFetchResponse(BaseModel):
    url: str
    host: str
    status_code: int
    content_type: str | None = None
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    fetched_at: datetime
    text: str
    truncated: bool
    risk_markers: list[str] = Field(default_factory=list)
    redirect_chain: list[str | None] = Field(default_factory=list, max_length=10)


class InternetScoutStoredResponse(BaseModel):
    request_id: UUID
    plan: InternetScoutPlan
    evidence: InternetEvidencePacket
