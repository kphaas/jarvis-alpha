"""Unit tests for Dream Temporal activities."""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal

from brain.dream import activities
from brain.dream.types import PersistPlanSpec, PlanSessionSpec, ReviewPlanSpec
from jarvis_common.dream_types import (
    AgentType,
    DreamPlan,
    IssueSeverity,
    ReviewIssue,
    ReviewerVerdict,
    ReviewResult,
    StepPlan,
)


class FakeRegistry:
    async def get(self, name: str, version: str = "v1") -> str:
        return f"{name}:{version}"


class FakeConn:
    def __init__(self):
        self.executed = []

    async def fetchrow(self, query, *args):
        return {
            "goal_type": "default",
            "planner_provider": "anthropic",
            "planner_model": "claude-haiku",
            "planner_family": "claude",
            "reviewer_provider": "google",
            "reviewer_model": "gemini-flash",
            "reviewer_family": "gemini",
            "max_revisions": 2,
            "cost_multiplier": Decimal("2.50"),
        }

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "OK"


def _plan() -> DreamPlan:
    return DreamPlan(
        reasoning="Read first, then draft.",
        steps=[
            StepPlan(
                step_index=1,
                name="read_context",
                description="Read the relevant files.",
                agent_type=AgentType.LLM,
                acceptance_criteria=["Context is summarized."],
                estimated_cost_usd=Decimal("0.01"),
            )
        ],
        total_estimated_cost_usd=Decimal("0.01"),
    )


def _plan_dict() -> dict:
    return {
        "reasoning": "Read first, then draft.",
        "steps": [
            {
                "step_index": 1,
                "name": "read_context",
                "description": "Read the relevant files.",
                "agent_type": "llm",
                "depends_on": [],
                "acceptance_criteria": ["Context is summarized."],
                "estimated_cost_usd": 0.01,
                "estimated_model": None,
            }
        ],
        "total_estimated_cost_usd": 0.01,
    }


def patch_activity_db(monkeypatch, conn):
    @asynccontextmanager
    async def fake_activity_db(user_id="system", role="platform_admin"):
        yield conn

    monkeypatch.setattr(activities, "activity_db", fake_activity_db)


async def test_plan_session_activity_calls_planner(monkeypatch):
    conn = FakeConn()
    patch_activity_db(monkeypatch, conn)
    monkeypatch.setattr(activities, "get_registry", lambda: FakeRegistry())
    calls = {}

    async def fake_plan(
        self,
        goal,
        system_prompt,
        recent_context=None,
        prior_lessons=None,
        revision_hint=None,
    ):
        calls.update(
            {
                "goal": goal,
                "system_prompt": system_prompt,
                "recent_context": recent_context,
                "prior_lessons": prior_lessons,
                "revision_hint": revision_hint,
            }
        )
        return _plan()

    monkeypatch.setattr(activities.ClaudePlanner, "plan", fake_plan)

    result = await activities.plan_session_activity(
        "dream:w:plan:1",
        PlanSessionSpec(
            session_id="7",
            user_id="ken",
            goal_type="default",
            goal_text="finish Dream Mode",
            recent_context="recent",
            prior_lessons="lessons",
            revision_hint="tighten ACs",
        ),
    )

    assert calls["goal"] == "finish Dream Mode"
    assert calls["system_prompt"] == "planner:v1"
    assert calls["recent_context"] == "recent"
    assert calls["prior_lessons"] == "lessons"
    assert calls["revision_hint"] == "tighten ACs"
    assert result.policy["max_revisions"] == 2
    assert result.plan["steps"][0]["name"] == "read_context"


async def test_review_plan_activity_calls_reviewer(monkeypatch):
    conn = FakeConn()
    patch_activity_db(monkeypatch, conn)
    monkeypatch.setattr(activities, "get_registry", lambda: FakeRegistry())
    calls = {}

    async def fake_review(self, plan, system_prompt):
        calls["plan"] = plan
        calls["system_prompt"] = system_prompt
        return ReviewResult(
            verdict=ReviewerVerdict.NEEDS_REVISION,
            reasoning="Needs a narrower first step.",
            issues=[
                ReviewIssue(
                    severity=IssueSeverity.MEDIUM,
                    step_index=1,
                    message="Too broad.",
                )
            ],
            revision_hint="Split the read step.",
        )

    monkeypatch.setattr(activities.GeminiReviewer, "review", fake_review)

    result = await activities.review_plan_activity(
        "dream:w:review:1",
        ReviewPlanSpec(
            session_id="7",
            user_id="ken",
            goal_type="default",
            plan=_plan_dict(),
        ),
    )

    assert calls["system_prompt"] == "reviewer:v1"
    assert calls["plan"].steps[0].name == "read_context"
    assert result.verdict == "NEEDS_REVISION"
    assert result.issues[0]["message"] == "Too broad."
    assert result.revision_hint == "Split the read step."


async def test_persist_plan_activity_replaces_steps_and_updates_session(monkeypatch):
    conn = FakeConn()
    patch_activity_db(monkeypatch, conn)

    result = await activities.persist_plan_activity(
        "dream:w:persist:7",
        PersistPlanSpec(
            session_id="7",
            plan=_plan_dict(),
            review={
                "verdict": "APPROVED",
                "reasoning": "Looks good.",
                "issues": [],
                "revision_hint": None,
            },
            replan_count=1,
        ),
    )

    assert result.step_count == 1
    queries = [query for query, _ in conn.executed]
    assert any("DELETE FROM alpha_dream_steps" in query for query in queries)
    assert any("INSERT INTO alpha_dream_steps" in query for query in queries)
    assert any("review_verdict" in query for query in queries)
