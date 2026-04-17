"""Shared dataclass types for Dream Mode across Brain and Gateway.

Single source of truth — no duplicate definitions between services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class AgentType(str, Enum):
    LLM = "llm"
    CODE = "code"
    TOOL = "tool"
    CLOUD = "cloud"


class ReviewerVerdict(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NEEDS_REVISION = "NEEDS_REVISION"


class IssueSeverity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class StepPlan:
    """A single step proposed by the planner."""

    step_index: int
    name: str
    description: str
    agent_type: AgentType
    depends_on: list[int] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    estimated_cost_usd: Decimal = Decimal("0")
    estimated_model: Optional[str] = None


@dataclass
class DreamPlan:
    """Complete plan from planner."""

    reasoning: str
    steps: list[StepPlan]
    total_estimated_cost_usd: Decimal


@dataclass
class ReviewIssue:
    severity: IssueSeverity
    step_index: Optional[int]
    message: str


@dataclass
class ReviewResult:
    """Output of reviewer."""

    verdict: ReviewerVerdict
    reasoning: str
    issues: list[ReviewIssue] = field(default_factory=list)
    revision_hint: Optional[str] = None


@dataclass
class ModelPolicy:
    """Loaded row from alpha_dream_model_policy."""

    goal_type: str
    planner_provider: str
    planner_model: str
    planner_family: str
    reviewer_provider: str
    reviewer_model: str
    reviewer_family: str
    max_revisions: int
    cost_multiplier: Decimal

    def validate_families_differ(self) -> None:
        """Hard check: planner and reviewer must be from different families."""
        if self.planner_family == self.reviewer_family:
            raise ValueError(
                f"ModelPolicy invariant violated: planner_family={self.planner_family} "
                f"== reviewer_family={self.reviewer_family}. Must differ."
            )
