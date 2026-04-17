"""Unit tests for reviewer schema parser + GeminiReviewer."""

import json

import pytest
from decimal import Decimal

from brain.services.reviewer import (
    GeminiReviewer,
    ReviewerSchemaError,
    parse_review_json,
)
from jarvis_common.dream_types import (
    IssueSeverity,
    ModelPolicy,
    ReviewerVerdict,
)


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


def test_parse_approved():
    raw = json.dumps(
        {
            "verdict": "APPROVED",
            "reasoning": "solid plan",
            "issues": [],
            "revision_hint": None,
        }
    )
    r = parse_review_json(raw)
    assert r.verdict == ReviewerVerdict.APPROVED
    assert r.revision_hint is None


def test_parse_rejected_with_issues():
    raw = json.dumps(
        {
            "verdict": "REJECTED",
            "reasoning": "unsafe",
            "issues": [
                {"severity": "high", "step_index": 1, "message": "modifies middleware"},
            ],
            "revision_hint": None,
        }
    )
    r = parse_review_json(raw)
    assert r.verdict == ReviewerVerdict.REJECTED
    assert len(r.issues) == 1
    assert r.issues[0].severity == IssueSeverity.HIGH


def test_parse_needs_revision_requires_hint():
    raw = json.dumps(
        {
            "verdict": "NEEDS_REVISION",
            "reasoning": "missing read step",
            "issues": [],
            "revision_hint": None,
        }
    )
    with pytest.raises(ReviewerSchemaError, match="revision_hint"):
        parse_review_json(raw)


def test_parse_needs_revision_valid():
    raw = json.dumps(
        {
            "verdict": "NEEDS_REVISION",
            "reasoning": "missing read step",
            "issues": [],
            "revision_hint": "add read step before step 3",
        }
    )
    r = parse_review_json(raw)
    assert r.verdict == ReviewerVerdict.NEEDS_REVISION
    assert r.revision_hint == "add read step before step 3"


def test_parse_invalid_verdict():
    raw = json.dumps({"verdict": "MAYBE", "reasoning": "...", "issues": []})
    with pytest.raises(ReviewerSchemaError, match="verdict"):
        parse_review_json(raw)


def test_parse_invalid_severity():
    raw = json.dumps(
        {
            "verdict": "REJECTED",
            "reasoning": "bad",
            "issues": [{"severity": "critical", "step_index": 1, "message": "x"}],
            "revision_hint": None,
        }
    )
    with pytest.raises(ReviewerSchemaError, match="severity"):
        parse_review_json(raw)


def test_parse_invalid_json():
    with pytest.raises(ReviewerSchemaError, match="Invalid JSON"):
        parse_review_json("nope")


def test_reviewer_name_and_family():
    r = GeminiReviewer(model="gemini-2.5-flash", policy=_policy())
    assert "gemini" in r.name
    assert r.family == "gemini"
