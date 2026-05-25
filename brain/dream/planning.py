"""Shared Dream planning helpers for routes and Temporal activities."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import asyncpg

from brain.services.planner import parse_plan_json
from brain.services.prompt_registry import MarkdownRegistry
from jarvis_common.dream_types import DreamPlan, ModelPolicy, ReviewResult

PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts" / "dream"
_registry: MarkdownRegistry | None = None


def get_registry() -> MarkdownRegistry:
    global _registry
    if _registry is None:
        _registry = MarkdownRegistry(root=PROMPTS_ROOT)
    return _registry


async def load_model_policy(conn: asyncpg.Connection, goal_type: str) -> ModelPolicy:
    row = await conn.fetchrow(
        """
        SELECT goal_type, planner_provider, planner_model, planner_family,
               reviewer_provider, reviewer_model, reviewer_family,
               max_revisions, cost_multiplier
        FROM alpha_dream_model_policy
        WHERE goal_type = $1
        """,
        goal_type,
    )
    if row is None:
        raise ValueError(f"No model policy for goal_type={goal_type}")
    policy = ModelPolicy(
        goal_type=row["goal_type"],
        planner_provider=row["planner_provider"],
        planner_model=row["planner_model"],
        planner_family=row["planner_family"],
        reviewer_provider=row["reviewer_provider"],
        reviewer_model=row["reviewer_model"],
        reviewer_family=row["reviewer_family"],
        max_revisions=row["max_revisions"],
        cost_multiplier=Decimal(str(row["cost_multiplier"])),
    )
    policy.validate_families_differ()
    return policy


def policy_to_dict(policy: ModelPolicy) -> dict:
    return {
        "goal_type": policy.goal_type,
        "planner_provider": policy.planner_provider,
        "planner_model": policy.planner_model,
        "planner_family": policy.planner_family,
        "reviewer_provider": policy.reviewer_provider,
        "reviewer_model": policy.reviewer_model,
        "reviewer_family": policy.reviewer_family,
        "max_revisions": policy.max_revisions,
        "cost_multiplier": float(policy.cost_multiplier),
    }


def plan_to_dict(plan: DreamPlan) -> dict:
    return {
        "reasoning": plan.reasoning,
        "steps": [
            {
                "step_index": s.step_index,
                "name": s.name,
                "description": s.description,
                "agent_type": s.agent_type.value,
                "depends_on": s.depends_on,
                "acceptance_criteria": s.acceptance_criteria,
                "estimated_cost_usd": float(s.estimated_cost_usd),
                "estimated_model": s.estimated_model,
            }
            for s in plan.steps
        ],
        "total_estimated_cost_usd": float(plan.total_estimated_cost_usd),
    }


def plan_from_dict(plan_json: dict) -> DreamPlan:
    return parse_plan_json(json.dumps(plan_json))


def review_to_dict(review: ReviewResult) -> dict:
    return {
        "verdict": review.verdict.value,
        "reasoning": review.reasoning,
        "issues": [
            {
                "severity": issue.severity.value,
                "step_index": issue.step_index,
                "message": issue.message,
            }
            for issue in review.issues
        ],
        "revision_hint": review.revision_hint,
    }
