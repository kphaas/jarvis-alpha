"""D3.3-specific DTOs for Dream Mode Temporal workflow.

Shared dream types (DreamPlan, StepPlan, ReviewResult, ReviewerVerdict,
ModelPolicy, AgentType) live in jarvis_common.dream_types. Import from
there, not here.

This file holds only DTOs that are specific to the D3.3 workflow layer:
workflow input, cleanup state, and final result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class DreamSessionInput:
    session_id: str
    user_id: str
    prompt: str
    context_ids: list[str] = field(default_factory=list)
    trigger: Literal["scheduled", "manual", "dry_run"] = "manual"


@dataclass
class CleanupSpec:
    session_id: str
    completed_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)
    final_status: Literal[
        "completed", "halted", "aborted", "killed", "failed", "running"
    ] = "running"
    halt_reason: str | None = None
    halt_severity: Literal["graceful", "fast", "emergency"] | None = None
    briefing_summary: str | None = None


@dataclass
class DreamSessionResult:
    session_id: str
    status: str
    halt_reason: str | None = None
    steps_completed: int = 0
    steps_failed: int = 0
    total_cost_usd: float = 0.0
