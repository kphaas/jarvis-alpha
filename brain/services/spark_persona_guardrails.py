"""Spark persona guardrail state.

The state is intentionally local-file backed for this phase: it is operator
configuration, not corpus content, and it must not require a schema migration
before the UI can make the current safety posture explicit.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SparkMode = Literal["draft_only", "hybrid_review", "auto_guarded"]
Sensitivity = Literal[
    "relationship",
    "minor",
    "family",
    "legal",
    "medical",
    "financial",
    "security",
    "custody",
]


class SparkProtectedRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,63}$")
    label: str = Field(min_length=1, max_length=80)
    relationship: str = Field(min_length=1, max_length=80)
    sensitivity: Sensitivity
    default_mode: SparkMode = "draft_only"
    approval_required: bool = True
    notes: str | None = Field(default=None, max_length=240)


class SparkPersonaCalibration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_voice: list[str] = Field(default_factory=list, max_length=20)
    avoid_voice: list[str] = Field(default_factory=list, max_length=20)
    signature_phrases: list[str] = Field(default_factory=list, max_length=20)
    response_length: Literal["short", "short_medium", "medium"] = "short_medium"
    uncertainty_policy: str = Field(min_length=1, max_length=280)
    escalation_style: str = Field(min_length=1, max_length=280)
    urgency_policy: str = Field(min_length=1, max_length=280)

    @field_validator("target_voice", "avoid_voice", "signature_phrases")
    @classmethod
    def _clean_list(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            item = value.strip()
            key = item.lower()
            if item and key not in seen:
                cleaned.append(item)
                seen.add(key)
        return cleaned


class SparkGuardrailState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str = Field(default="ken", min_length=1, max_length=64)
    active_mode: SparkMode = "draft_only"
    auto_send_enabled: bool = False
    protected_topics: list[Sensitivity] = Field(default_factory=list, min_length=1)
    protected_relationships: list[SparkProtectedRelationship] = Field(
        default_factory=list,
        min_length=1,
    )
    calibration: SparkPersonaCalibration
    updated_at: str = Field(default_factory=lambda: _utc_now_iso())

    @model_validator(mode="after")
    def _phase_safety(self) -> "SparkGuardrailState":
        if self.auto_send_enabled:
            raise ValueError("auto_send_enabled is not available in this Spark phase")
        return self


def guardrail_state_path() -> Path:
    raw_path = os.environ.get("SPARK_GUARDRAIL_STATE_PATH", "").strip()
    if raw_path:
        return Path(raw_path).expanduser()
    return Path("~/jarvis/spark/guardrails/ken.json").expanduser()


def load_spark_guardrails(path: Path | None = None) -> SparkGuardrailState:
    state_path = path or guardrail_state_path()
    if not state_path.exists():
        return default_spark_guardrails()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    return SparkGuardrailState.model_validate(payload)


def save_spark_guardrails(
    state: SparkGuardrailState,
    path: Path | None = None,
) -> SparkGuardrailState:
    state_path = path or guardrail_state_path()
    saved = state.model_copy(update={"updated_at": _utc_now_iso()})
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_path = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
    tmp_path.write_text(
        json.dumps(saved.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.chmod(0o600)
    os.replace(tmp_path, state_path)
    state_path.chmod(0o600)
    return saved


def default_spark_guardrails() -> SparkGuardrailState:
    return SparkGuardrailState(
        protected_topics=[
            "legal",
            "medical",
            "custody",
            "minor",
            "relationship",
            "financial",
            "security",
        ],
        protected_relationships=[
            SparkProtectedRelationship(
                id="ryleigh",
                label="Ryleigh",
                relationship="child",
                sensitivity="minor",
                notes="Draft-only until Ken explicitly approves a relationship policy.",
            ),
            SparkProtectedRelationship(
                id="sloane",
                label="Sloane",
                relationship="child",
                sensitivity="minor",
                notes="Draft-only until Ken explicitly approves a relationship policy.",
            ),
            SparkProtectedRelationship(
                id="sweta",
                label="Sweta",
                relationship="partner",
                sensitivity="relationship",
                default_mode="hybrid_review",
            ),
            SparkProtectedRelationship(
                id="meagan",
                label="Meagan",
                relationship="co-parent",
                sensitivity="custody",
            ),
            SparkProtectedRelationship(
                id="mother",
                label="Mother",
                relationship="parent",
                sensitivity="family",
            ),
        ],
        calibration=SparkPersonaCalibration(
            target_voice=[
                "optimistic",
                "cheerful",
                "playful",
                "smart",
                "thoughtful",
                "composed",
                "sharp",
                "witty",
            ],
            avoid_voice=[
                "robotic",
                "rambling",
                "vague",
                "salesy",
                "servile",
                "angry",
                "condescending",
            ],
            signature_phrases=[
                "cheers",
                "fair enough",
                "this is the way",
                "Do it right the first time",
                "best of breed",
                "ohana",
            ],
            uncertainty_policy=(
                "Use available tools or an LLM check to improve certainty; "
                "if still uncertain, say so plainly."
            ),
            escalation_style="Kind, direct, tactful, and genuine.",
            urgency_policy="Acknowledge urgency and give a clear timeline.",
        ),
    )


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
