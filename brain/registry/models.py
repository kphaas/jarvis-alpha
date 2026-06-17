"""Typed registry models for Alpha skills and agents."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ApprovalTier = Literal["T1", "T2", "T3", "T4", "T5"]
RegistryStatus = Literal["planned", "active", "disabled"]
AgentRiskTier = Literal["T1", "T2", "T3", "T4", "T5"]
DataClassification = Literal[
    "none",
    "ops",
    "personal",
    "message_body",
    "child",
    "financial",
    "medical",
    "security",
]
SideEffectClass = Literal[
    "read",
    "write",
    "external_send",
    "physical_world",
    "operator_notification",
    "control_plane",
]
EgressMode = Literal["none", "gateway", "local", "tailscale"]
CostMode = Literal["none", "local", "cloud"]

_SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
_AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class SkillRuntimeManifest(BaseModel):
    timeout_s: int = Field(ge=1, le=3600)
    retry_policy: str = Field(min_length=1, max_length=64)
    rate_limit: str = Field(min_length=1, max_length=64)


class SkillCostManifest(BaseModel):
    mode: CostMode = "none"
    max_usd_per_call: float = Field(default=0.0, ge=0)
    model_policy: str | None = Field(default=None, max_length=96)


class SkillEgressManifest(BaseModel):
    mode: EgressMode = "none"
    provider: str | None = Field(default=None, max_length=96)
    data_source_id: str | None = Field(
        default=None,
        max_length=96,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    allowed_hosts: list[str] = Field(default_factory=list)


class SkillAuditManifest(BaseModel):
    event_name: str = Field(
        min_length=1,
        max_length=96,
        pattern=r"^[a-z][a-z0-9_]*(?:[._][a-z][a-z0-9_]*)*$",
    )
    redact_fields: list[str] = Field(default_factory=list)


class SkillManifestV1(BaseModel):
    """Governance metadata every skill must carry.

    The manifest makes the registry useful as an operational control plane, not
    just a list of names. It intentionally stores compact policy facts instead
    of provider credentials or implementation details.
    """

    manifest_version: Literal[1] = 1
    data_classification: DataClassification
    side_effect_class: SideEffectClass
    input_schema_ref: str = Field(min_length=1, max_length=160)
    output_schema_ref: str = Field(min_length=1, max_length=160)
    runtime: SkillRuntimeManifest
    cost: SkillCostManifest
    egress: SkillEgressManifest
    audit: SkillAuditManifest
    compensation: str = Field(min_length=1, max_length=160)
    test_ref: str = Field(min_length=1, max_length=200)
    runbook_ref: str = Field(min_length=1, max_length=200)


class SkillSpec(BaseModel):
    name: str
    domain: str
    action: str
    description: str
    approval_tier: ApprovalTier
    scope: str
    status: RegistryStatus = "planned"
    mutates_state: bool = False
    body_access: bool = False
    idempotency_required: bool = False
    owner: str = "ken"
    metadata: dict = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _SKILL_NAME_RE.match(value):
            raise ValueError("skill name must be <domain>.<action> snake_case")
        return value

    @field_validator("domain", "action", "scope")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must be non-empty")
        return value

    @model_validator(mode="after")
    def validate_name_parts(self) -> "SkillSpec":
        if self.name != f"{self.domain}.{self.action}":
            raise ValueError("skill name must equal domain.action")
        manifest = self.metadata.get("manifest")
        if manifest is None:
            raise ValueError("skill metadata must include manifest v1")
        parsed = SkillManifestV1.model_validate(manifest)
        if self.body_access and parsed.data_classification != "message_body":
            raise ValueError("body_access skills must use message_body classification")
        if self.mutates_state and parsed.side_effect_class == "read":
            raise ValueError("mutating skills cannot use read side_effect_class")
        if not self.mutates_state and parsed.side_effect_class != "read":
            raise ValueError("read-only skills must use read side_effect_class")
        return self


class AgentSpec(BaseModel):
    agent_id: str
    display_name: str
    purpose: str
    risk_tier: AgentRiskTier
    status: RegistryStatus = "planned"
    enabled: bool = False
    owner: str = "ken"
    cadence: str | None = None
    launch_label: str | None = None
    allowed_skills: list[str] = Field(default_factory=list)
    allowed_scopes: list[str] = Field(default_factory=list)
    cost_daily_cap_usd: float | None = None
    model_policy: dict = Field(default_factory=dict)
    approval_policy: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)

    @field_validator("agent_id")
    @classmethod
    def validate_agent_id(cls, value: str) -> str:
        if not _AGENT_ID_RE.match(value):
            raise ValueError("agent_id must be snake_case")
        return value

    @field_validator("allowed_skills")
    @classmethod
    def validate_allowed_skills(cls, value: list[str]) -> list[str]:
        for skill_name in value:
            if not _SKILL_NAME_RE.match(skill_name):
                raise ValueError(f"invalid allowed skill name: {skill_name}")
        return value

    @field_validator("allowed_scopes")
    @classmethod
    def validate_allowed_scopes(cls, value: list[str]) -> list[str]:
        for scope in value:
            if not scope.strip():
                raise ValueError("allowed scopes must be non-empty")
        return value

    @field_validator("cost_daily_cap_usd")
    @classmethod
    def validate_cost_cap(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("cost_daily_cap_usd must be non-negative")
        return value
