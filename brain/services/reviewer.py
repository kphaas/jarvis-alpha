"""Reviewer service — validates DreamPlan via different-family LLM.

IReviewer abstracts the LLM backend. GeminiReviewer uses Gateway's Gemini adapter.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

from jarvis_common.dream_types import (
    DreamPlan,
    IssueSeverity,
    ModelPolicy,
    ReviewerVerdict,
    ReviewIssue,
    ReviewResult,
)

log = logging.getLogger(__name__)


class ReviewerError(Exception):
    pass


class ReviewerSchemaError(ReviewerError):
    pass


class IReviewer(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def family(self) -> str: ...

    @abstractmethod
    async def review(
        self,
        plan: DreamPlan,
        system_prompt: str,
    ) -> ReviewResult: ...


def _strip_json_wrapping(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return text


def parse_review_json(raw: str) -> ReviewResult:
    """Parse reviewer LLM JSON into ReviewResult. Raises ReviewerSchemaError on issue."""
    raw = _strip_json_wrapping(raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ReviewerSchemaError(f"Invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise ReviewerSchemaError("Top-level output must be JSON object")

    verdict_raw = data.get("verdict")
    try:
        verdict = ReviewerVerdict(verdict_raw)
    except ValueError as e:
        raise ReviewerSchemaError(f"Invalid verdict: {verdict_raw}") from e

    reasoning = data.get("reasoning")
    if not isinstance(reasoning, str):
        raise ReviewerSchemaError("Missing or invalid 'reasoning'")

    issues_raw = data.get("issues", [])
    if not isinstance(issues_raw, list):
        raise ReviewerSchemaError("'issues' must be a list")

    issues: list[ReviewIssue] = []
    for i, item in enumerate(issues_raw):
        if not isinstance(item, dict):
            raise ReviewerSchemaError(f"Issue {i}: not an object")
        sev_raw = item.get("severity")
        try:
            sev = IssueSeverity(sev_raw)
        except ValueError as e:
            raise ReviewerSchemaError(f"Issue {i}: invalid severity={sev_raw}") from e
        step_index = item.get("step_index")
        if step_index is not None and not isinstance(step_index, int):
            raise ReviewerSchemaError(f"Issue {i}: step_index must be int or null")
        message = item.get("message", "")
        if not isinstance(message, str):
            raise ReviewerSchemaError(f"Issue {i}: message must be string")
        issues.append(ReviewIssue(severity=sev, step_index=step_index, message=message))

    revision_hint = data.get("revision_hint")
    if revision_hint is not None and not isinstance(revision_hint, str):
        raise ReviewerSchemaError("revision_hint must be string or null")

    if verdict == ReviewerVerdict.NEEDS_REVISION and not revision_hint:
        raise ReviewerSchemaError(
            "NEEDS_REVISION verdict requires non-empty revision_hint"
        )

    return ReviewResult(
        verdict=verdict,
        reasoning=reasoning,
        issues=issues,
        revision_hint=revision_hint,
    )


class GeminiReviewer(IReviewer):
    """Gemini-family reviewer via Gateway's Gemini adapter.

    STUB — HTTP call wiring added in CloudReviewerMixin below.
    """

    def __init__(self, model: str, policy: ModelPolicy):
        self._model = model
        self._policy = policy

    @property
    def name(self) -> str:
        return f"gemini:{self._model}"

    @property
    def family(self) -> str:
        return self._policy.reviewer_family

    async def review(self, plan: DreamPlan, system_prompt: str) -> ReviewResult:
        from brain.services.llm_transport import call_gateway_cloud

        user_msg = _format_plan_for_reviewer(plan)
        raw = await call_gateway_cloud(
            provider=self._policy.reviewer_provider,
            model=self._policy.reviewer_model,
            system_prompt=system_prompt,
            user_message=user_msg,
            max_tokens=2000,
        )
        return parse_review_json(raw)


def _format_plan_for_reviewer(plan: DreamPlan) -> str:
    """Serialize a DreamPlan for the reviewer prompt user_message."""

    plan_dict = {
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
    return f"Review this plan:\n\n{json.dumps(plan_dict, indent=2)}"
