"""DTOs for Dream Mode Temporal workflow — inputs, outputs, and intermediate state."""

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
class DreamStep:
    step_id: str
    kind: Literal["ollama", "claude", "memory_read", "memory_write", "search"]
    instruction: str
    budget_usd: float = 0.0


@dataclass
class DreamPlan:
    plan_hash: str
    steps: list[DreamStep]


@dataclass
class CostRecord:
    session_id: str
    step_id: str
    provider: Literal["anthropic", "gemini", "perplexity"]
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    idempotency_key: str
    on_behalf_of: str
    executor: Literal["dream"] = "dream"


@dataclass
class StepResult:
    step_id: str
    output: dict
    cost_record: CostRecord
    success: bool = True
    error: str | None = None


@dataclass
class ReviewResult:
    approved: bool
    reason: str
    violations: list[str] = field(default_factory=list)


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
