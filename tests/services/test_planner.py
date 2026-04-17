"""Unit tests for planner schema parser + ClaudePlanner stub."""

import json
from decimal import Decimal

import pytest

from brain.services.planner import (
    ClaudePlanner,
    PlannerSchemaError,
    parse_plan_json,
)
from jarvis_common.dream_types import (
    AgentType,
    ModelPolicy,
)


def _valid_plan_dict():
    return {
        "reasoning": "approach",
        "steps": [
            {
                "step_index": 1,
                "name": "read_file",
                "description": "read it",
                "agent_type": "tool",
                "depends_on": [],
                "acceptance_criteria": ["file read"],
                "estimated_cost_usd": 0.0,
                "estimated_model": None,
            },
            {
                "step_index": 2,
                "name": "draft_patch",
                "description": "draft",
                "agent_type": "llm",
                "depends_on": [1],
                "acceptance_criteria": ["patch drafted"],
                "estimated_cost_usd": 0.02,
                "estimated_model": "claude-haiku",
            },
        ],
        "total_estimated_cost_usd": 0.02,
    }


def _policy():
    return ModelPolicy(
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


def test_parse_valid_plan():
    plan = parse_plan_json(json.dumps(_valid_plan_dict()))
    assert plan.reasoning == "approach"
    assert len(plan.steps) == 2
    assert plan.steps[0].agent_type == AgentType.TOOL
    assert plan.total_estimated_cost_usd == Decimal("0.02")


def test_parse_invalid_json():
    with pytest.raises(PlannerSchemaError, match="Invalid JSON"):
        parse_plan_json("not json")


def test_parse_missing_reasoning():
    d = _valid_plan_dict()
    del d["reasoning"]
    with pytest.raises(PlannerSchemaError, match="reasoning"):
        parse_plan_json(json.dumps(d))


def test_parse_empty_steps():
    d = _valid_plan_dict()
    d["steps"] = []
    with pytest.raises(PlannerSchemaError, match="steps"):
        parse_plan_json(json.dumps(d))


def test_parse_too_many_steps():
    d = _valid_plan_dict()
    d["steps"] = [
        {
            "step_index": i + 1,
            "name": f"s{i}",
            "description": "d",
            "agent_type": "tool",
            "depends_on": [],
            "acceptance_criteria": ["ac"],
            "estimated_cost_usd": 0.0,
        }
        for i in range(16)
    ]
    d["total_estimated_cost_usd"] = 0.0
    with pytest.raises(PlannerSchemaError, match="Too many steps"):
        parse_plan_json(json.dumps(d))


def test_parse_duplicate_step_index():
    d = _valid_plan_dict()
    d["steps"][1]["step_index"] = 1
    with pytest.raises(PlannerSchemaError, match="Duplicate"):
        parse_plan_json(json.dumps(d))


def test_parse_forward_reference_rejected():
    d = _valid_plan_dict()
    d["steps"][0]["depends_on"] = [2]
    with pytest.raises(PlannerSchemaError, match="forward refs"):
        parse_plan_json(json.dumps(d))


def test_parse_invalid_agent_type():
    d = _valid_plan_dict()
    d["steps"][0]["agent_type"] = "magic"
    with pytest.raises(PlannerSchemaError, match="agent_type"):
        parse_plan_json(json.dumps(d))


def test_parse_missing_ac():
    d = _valid_plan_dict()
    d["steps"][0]["acceptance_criteria"] = []
    with pytest.raises(PlannerSchemaError, match="acceptance_criteria"):
        parse_plan_json(json.dumps(d))


def test_parse_negative_cost_rejected():
    d = _valid_plan_dict()
    d["steps"][0]["estimated_cost_usd"] = -0.01
    with pytest.raises(PlannerSchemaError, match=">= 0"):
        parse_plan_json(json.dumps(d))


def test_parse_cost_mismatch_rejected():
    d = _valid_plan_dict()
    d["total_estimated_cost_usd"] = 99.99
    with pytest.raises(PlannerSchemaError, match="sum of steps"):
        parse_plan_json(json.dumps(d))


def test_claude_planner_stub_raises():
    planner = ClaudePlanner(model="claude-haiku-4-5-20251001", policy=_policy())
    assert planner.name == "claude:claude-haiku-4-5-20251001"
    assert planner.family == "claude"


async def test_claude_planner_plan_calls_gateway_and_parses(monkeypatch):
    from unittest.mock import patch
    import json as _json

    monkeypatch.setenv("ALPHA_BRAIN_SERVICE_TOKEN", "test-token")
    planner = ClaudePlanner(model="claude-haiku", policy=_policy())

    fake_plan_json = _json.dumps(_valid_plan_dict())
    with patch(
        "brain.services.llm_transport._post_sync",
        return_value=(0, _json.dumps({"content": fake_plan_json})),
    ):
        result = await planner.plan(
            goal="fix the bug", system_prompt="you are a planner"
        )

    assert result.reasoning == "approach"
    assert len(result.steps) == 2


async def test_claude_planner_propagates_transport_error(monkeypatch):
    from unittest.mock import patch
    from brain.services.llm_transport import GatewayTransportError

    monkeypatch.setenv("ALPHA_BRAIN_SERVICE_TOKEN", "test-token")
    planner = ClaudePlanner(model="claude-haiku", policy=_policy())

    with patch(
        "brain.services.llm_transport._post_sync",
        return_value=(7, ""),
    ):
        with pytest.raises(GatewayTransportError):
            await planner.plan(goal="g", system_prompt="p")
