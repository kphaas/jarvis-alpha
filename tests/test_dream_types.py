"""Unit tests for shared dream types."""

from decimal import Decimal

import pytest

from jarvis_common.dream_types import (
    AgentType,
    IssueSeverity,
    ModelPolicy,
    ReviewerVerdict,
    StepPlan,
)


def test_agent_type_enum_values():
    assert AgentType.LLM.value == "llm"
    assert AgentType("code") == AgentType.CODE


def test_reviewer_verdict_enum():
    assert ReviewerVerdict.APPROVED.value == "APPROVED"
    assert ReviewerVerdict("REJECTED") == ReviewerVerdict.REJECTED


def test_issue_severity_enum():
    assert IssueSeverity.HIGH.value == "high"


def test_step_plan_defaults():
    s = StepPlan(
        step_index=1,
        name="foo",
        description="bar",
        agent_type=AgentType.LLM,
    )
    assert s.depends_on == []
    assert s.acceptance_criteria == []
    assert s.estimated_cost_usd == Decimal("0")
    assert s.estimated_model is None


def test_model_policy_validates_different_families():
    p = ModelPolicy(
        goal_type="default",
        planner_provider="anthropic",
        planner_model="claude-haiku",
        planner_family="claude",
        reviewer_provider="google",
        reviewer_model="gemini-flash",
        reviewer_family="gemini",
        max_revisions=3,
        cost_multiplier=Decimal("2.5"),
    )
    p.validate_families_differ()


def test_model_policy_rejects_same_family():
    p = ModelPolicy(
        goal_type="bad",
        planner_provider="anthropic",
        planner_model="claude-haiku",
        planner_family="claude",
        reviewer_provider="anthropic",
        reviewer_model="claude-opus",
        reviewer_family="claude",
        max_revisions=3,
        cost_multiplier=Decimal("2.5"),
    )
    with pytest.raises(ValueError, match="invariant violated"):
        p.validate_families_differ()
