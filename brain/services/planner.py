"""Planner service — converts goals into DreamPlan DAGs via LLM.

IPlanner abstracts the LLM backend so models swap without route changes.
ClaudePlanner uses Gateway's Claude adapter (HTTP — wired in D2-c).
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional

from jarvis_common.dream_types import (
    AgentType,
    DreamPlan,
    ModelPolicy,
    StepPlan,
)

log = logging.getLogger(__name__)


class PlannerError(Exception):
    """Base exception for planner failures."""


class PlannerSchemaError(PlannerError):
    """LLM output failed schema validation."""


class IPlanner(ABC):
    """Abstract planner backend."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def family(self) -> str: ...

    @abstractmethod
    async def plan(
        self,
        goal: str,
        system_prompt: str,
        recent_context: Optional[str] = None,
        prior_lessons: Optional[str] = None,
        revision_hint: Optional[str] = None,
    ) -> DreamPlan:
        """Produce a DreamPlan for the given goal.

        Raises PlannerSchemaError if LLM output cannot be parsed.
        """
        ...


def parse_plan_json(raw: str) -> DreamPlan:
    """Parse planner LLM JSON output into DreamPlan. Raises PlannerSchemaError on any issue."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PlannerSchemaError(f"Invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise PlannerSchemaError("Top-level output must be JSON object")

    reasoning = data.get("reasoning")
    if not isinstance(reasoning, str):
        raise PlannerSchemaError("Missing or invalid 'reasoning'")

    steps_raw = data.get("steps")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise PlannerSchemaError("Missing or empty 'steps'")

    if len(steps_raw) > 15:
        raise PlannerSchemaError(f"Too many steps: {len(steps_raw)} (max 15)")

    steps: list[StepPlan] = []
    seen_indices: set[int] = set()

    for i, s in enumerate(steps_raw):
        if not isinstance(s, dict):
            raise PlannerSchemaError(f"Step {i}: not a JSON object")

        idx = s.get("step_index")
        if not isinstance(idx, int) or idx < 1:
            raise PlannerSchemaError(f"Step {i}: invalid step_index={idx}")
        if idx in seen_indices:
            raise PlannerSchemaError(f"Duplicate step_index={idx}")
        seen_indices.add(idx)

        name = s.get("name")
        if not isinstance(name, str) or not name.strip():
            raise PlannerSchemaError(f"Step {idx}: invalid 'name'")

        description = s.get("description", "")
        if not isinstance(description, str):
            raise PlannerSchemaError(f"Step {idx}: invalid 'description'")

        agent_type_raw = s.get("agent_type")
        try:
            agent_type = AgentType(agent_type_raw)
        except ValueError as e:
            raise PlannerSchemaError(
                f"Step {idx}: invalid agent_type={agent_type_raw}"
            ) from e

        depends_on = s.get("depends_on", [])
        if not isinstance(depends_on, list) or not all(
            isinstance(x, int) for x in depends_on
        ):
            raise PlannerSchemaError(f"Step {idx}: depends_on must be list of ints")

        for dep in depends_on:
            if dep >= idx:
                raise PlannerSchemaError(
                    f"Step {idx}: depends_on={dep} must be < step_index (no forward refs)"
                )

        ac = s.get("acceptance_criteria", [])
        if not isinstance(ac, list) or not ac:
            raise PlannerSchemaError(
                f"Step {idx}: must have at least one acceptance_criteria"
            )
        if not all(isinstance(x, str) and x.strip() for x in ac):
            raise PlannerSchemaError(
                f"Step {idx}: acceptance_criteria must be non-empty strings"
            )

        cost_raw = s.get("estimated_cost_usd", 0)
        if not isinstance(cost_raw, (int, float)):
            raise PlannerSchemaError(f"Step {idx}: estimated_cost_usd must be numeric")
        cost = Decimal(str(cost_raw))
        if cost < 0:
            raise PlannerSchemaError(f"Step {idx}: estimated_cost_usd must be >= 0")

        estimated_model = s.get("estimated_model")
        if estimated_model is not None and not isinstance(estimated_model, str):
            raise PlannerSchemaError(
                f"Step {idx}: estimated_model must be string or null"
            )

        steps.append(
            StepPlan(
                step_index=idx,
                name=name.strip(),
                description=description,
                agent_type=agent_type,
                depends_on=depends_on,
                acceptance_criteria=ac,
                estimated_cost_usd=cost,
                estimated_model=estimated_model,
            )
        )

    total_raw = data.get("total_estimated_cost_usd", 0)
    if not isinstance(total_raw, (int, float)):
        raise PlannerSchemaError("total_estimated_cost_usd must be numeric")
    total = Decimal(str(total_raw))

    summed = sum((s.estimated_cost_usd for s in steps), Decimal("0"))
    if abs(total - summed) > Decimal("0.01"):
        raise PlannerSchemaError(
            f"total_estimated_cost_usd={total} does not match sum of steps={summed}"
        )

    return DreamPlan(reasoning=reasoning, steps=steps, total_estimated_cost_usd=total)


class ClaudePlanner(IPlanner):
    """Planner backed by Claude via Gateway adapter.

    STUB for D2-b: returns raise NotImplementedError for plan().
    D2-c wires the HTTP call to Gateway's /v1/cloud/call.
    """

    def __init__(self, model: str, policy: ModelPolicy):
        self._model = model
        self._policy = policy

    @property
    def name(self) -> str:
        return f"claude:{self._model}"

    @property
    def family(self) -> str:
        return self._policy.planner_family

    async def plan(
        self,
        goal: str,
        system_prompt: str,
        recent_context: Optional[str] = None,
        prior_lessons: Optional[str] = None,
        revision_hint: Optional[str] = None,
    ) -> DreamPlan:
        from brain.services.llm_transport import call_gateway_cloud

        user_msg_parts = [f"GOAL:\n{goal}"]
        if recent_context:
            user_msg_parts.append(f"\nRECENT_CONTEXT:\n{recent_context}")
        if prior_lessons:
            user_msg_parts.append(f"\nPRIOR_LESSONS:\n{prior_lessons}")
        if revision_hint:
            user_msg_parts.append(
                f"\nREVISION_HINT (address this from prior reviewer rejection):\n{revision_hint}"
            )
        user_msg = "\n".join(user_msg_parts)

        raw = await call_gateway_cloud(
            provider=self._policy.planner_provider,
            model=self._policy.planner_model,
            system_prompt=system_prompt,
            user_message=user_msg,
            max_tokens=3000,
            temperature=0.3,
        )
        return parse_plan_json(raw)
