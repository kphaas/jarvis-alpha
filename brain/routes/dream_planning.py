"""Dream Mode plan + review routes.

POST /v1/dream/plan    — planner produces DreamPlan
POST /v1/dream/review  — reviewer validates DreamPlan

Both routes enforce cross-family model policy at Python layer
(belt-and-suspenders on DB CHECK constraint).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Optional

import asyncpg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from brain.db.pool import get_pool
from brain.middleware.scopes import check_scopes
from brain.services.planner import (
    ClaudePlanner,
    PlannerError,
    parse_plan_json,
)
from brain.services.prompt_registry import (
    MarkdownRegistry,
    PromptNotFoundError,
)
from brain.services.reviewer import (
    GeminiReviewer,
    ReviewerError,
)
from jarvis_common.dream_types import (
    DreamPlan,
    ModelPolicy,
)
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")
dream_planning_router = APIRouter(prefix="/v1/dream", tags=["dream-planning"])


PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts" / "dream"
_registry: Optional[MarkdownRegistry] = None


def _get_registry() -> MarkdownRegistry:
    global _registry
    if _registry is None:
        _registry = MarkdownRegistry(root=PROMPTS_ROOT)
    return _registry


class PlanRequest(BaseModel):
    goal_type: str = Field(default="default")
    goal_text: str
    recent_context: Optional[str] = None
    prior_lessons: Optional[str] = None
    revision_hint: Optional[str] = None
    prompt_version: str = Field(default="v1")


class ReviewRequest(BaseModel):
    goal_type: str = Field(default="default")
    plan_json: dict
    prompt_version: str = Field(default="v1")


async def _load_policy(pool: asyncpg.Pool, goal_type: str) -> ModelPolicy:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT set_config('rls.role', 'platform_admin', true)")
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
        raise HTTPException(
            status_code=404,
            detail=f"No model policy for goal_type={goal_type}",
        )
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
    try:
        policy.validate_families_differ()
    except ValueError as e:
        logger.error("dream_plan policy family violation: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Model policy corrupt: {e}",
        )
    return policy


def _plan_to_dict(plan: DreamPlan) -> dict:
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


@dream_planning_router.post("/plan")
async def create_plan(request: Request, req: PlanRequest):
    check_scopes(request, "dream.plan")
    pool = get_pool()
    policy = await _load_policy(pool, req.goal_type)

    try:
        system_prompt = await _get_registry().get("planner", version=req.prompt_version)
    except PromptNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"Prompt missing: {e}")

    planner = ClaudePlanner(model=policy.planner_model, policy=policy)

    try:
        plan = await planner.plan(
            goal=req.goal_text,
            system_prompt=system_prompt,
            recent_context=req.recent_context,
            prior_lessons=req.prior_lessons,
            revision_hint=req.revision_hint,
        )
    except PlannerError as e:
        logger.error("dream_plan planner error: %s", e)
        raise HTTPException(status_code=502, detail=f"Planner failed: {e}")

    logger.info(
        "dream_plan created goal_type=%s steps=%d cost=%s",
        req.goal_type,
        len(plan.steps),
        plan.total_estimated_cost_usd,
    )
    return {
        "plan": _plan_to_dict(plan),
        "policy": {
            "planner": f"{policy.planner_provider}:{policy.planner_model}",
            "reviewer": f"{policy.reviewer_provider}:{policy.reviewer_model}",
            "max_revisions": policy.max_revisions,
            "cost_multiplier": float(policy.cost_multiplier),
        },
    }


def _plan_from_dict(d: dict) -> DreamPlan:
    """Rehydrate DreamPlan from POSTed dict via parse_plan_json."""
    return parse_plan_json(json.dumps(d))


@dream_planning_router.post("/review")
async def create_review(request: Request, req: ReviewRequest):
    check_scopes(request, "dream.review")
    pool = get_pool()
    policy = await _load_policy(pool, req.goal_type)

    try:
        plan = _plan_from_dict(req.plan_json)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid plan_json: {e}")

    try:
        system_prompt = await _get_registry().get(
            "reviewer", version=req.prompt_version
        )
    except PromptNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"Prompt missing: {e}")

    reviewer = GeminiReviewer(model=policy.reviewer_model, policy=policy)

    try:
        review = await reviewer.review(plan=plan, system_prompt=system_prompt)
    except ReviewerError as e:
        logger.error("dream_review reviewer error: %s", e)
        raise HTTPException(status_code=502, detail=f"Reviewer failed: {e}")

    logger.info(
        "dream_review verdict=%s goal_type=%s issues=%d",
        review.verdict.value,
        req.goal_type,
        len(review.issues),
    )
    return {
        "verdict": review.verdict.value,
        "reasoning": review.reasoning,
        "issues": [
            {
                "severity": i.severity.value,
                "step_index": i.step_index,
                "message": i.message,
            }
            for i in review.issues
        ],
        "revision_hint": review.revision_hint,
    }
