"""Unit tests for brain/routes/review.py — pure helpers.

Covers service-scope enforcement, prompt builder, JSON-response parser
(including markdown-fence tolerance and malformed input), and overall-verdict
classification.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://user:pass@localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://user:pass@localhost/db")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://user:pass@localhost/db")
os.environ.setdefault("ALPHA_GATEWAY_URL", "https://localhost:8283")

import brain.routes.review as review_route
from brain.routes.review import (
    CriterionVerdict,
    ReviewRequest,
    _assert_review_service,
    _build_prompt,
    _overall_verdict,
    _parse_review_response,
    _strip_fences,
)


# ── Service auth enforcement ───────────────────────────────────────


def test_assert_review_service_accepts_current_sandbox_forge_token():
    _assert_review_service(
        iss="sandbox",
        actor_type="service",
        scopes=["forge.deploy.submit", "forge.llm.call"],
    )


def test_assert_review_service_accepts_future_forge_token():
    _assert_review_service(
        iss="forge",
        actor_type="service",
        scopes=["forge.llm.call"],
    )


def test_assert_review_service_rejects_user_even_with_scope():
    with pytest.raises(HTTPException) as exc:
        _assert_review_service(
            iss="user",
            actor_type="user",
            scopes=["forge.llm.call"],
        )
    assert exc.value.status_code == 403


def test_assert_review_service_rejects_service_missing_scope():
    with pytest.raises(HTTPException) as exc:
        _assert_review_service(
            iss="sandbox",
            actor_type="service",
            scopes=["health.read"],
        )
    assert exc.value.status_code == 403


# ── Prompt builder ─────────────────────────────────────────────────


def test_build_prompt_contains_spec_diff_and_criteria():
    p = _build_prompt("F-X-001", "diff body here", ["c1", "c2"])
    assert "F-X-001" in p
    assert "diff body here" in p
    assert "c1" in p
    assert "c2" in p
    assert "JSON" in p


def test_build_prompt_handles_empty_criteria():
    p = _build_prompt("F-X-002", "diff", [])
    assert "(none)" in p


# ── Fence stripping ────────────────────────────────────────────────


def test_strip_fences_passthrough():
    assert _strip_fences('{"a": 1}') == '{"a": 1}'


def test_strip_fences_json_fence():
    assert _strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_fences_plain_fence():
    assert _strip_fences('```\n{"a": 1}\n```') == '{"a": 1}'


# ── Parser ─────────────────────────────────────────────────────────


def test_parse_response_all_pass():
    raw = json.dumps(
        {
            "criteria": [
                {"criterion": "c1", "pass": True, "notes": "ok"},
                {"criterion": "c2", "pass": True, "notes": "fine"},
            ]
        }
    )
    parsed = _parse_review_response(raw)
    assert len(parsed) == 2
    assert all(c.pass_ for c in parsed)


def test_parse_response_mixed_verdict():
    raw = json.dumps(
        {
            "criteria": [
                {"criterion": "c1", "pass": True, "notes": ""},
                {"criterion": "c2", "pass": False, "notes": "missing assertion"},
            ]
        }
    )
    parsed = _parse_review_response(raw)
    assert parsed[0].pass_ is True
    assert parsed[1].pass_ is False
    assert parsed[1].notes == "missing assertion"


def test_parse_response_with_markdown_fence():
    raw = '```json\n{"criteria": [{"criterion": "c1", "pass": true, "notes": ""}]}\n```'
    parsed = _parse_review_response(raw)
    assert len(parsed) == 1
    assert parsed[0].pass_ is True


def test_parse_response_invalid_json_raises():
    with pytest.raises(ValueError, match="non-JSON"):
        _parse_review_response("definitely not json")


def test_parse_response_missing_criteria_key_raises():
    with pytest.raises(ValueError, match="criteria"):
        _parse_review_response('{"verdict": "pass"}')


def test_parse_response_skips_non_dict_items():
    raw = json.dumps({"criteria": [{"criterion": "c1", "pass": True}, "garbage", 42]})
    parsed = _parse_review_response(raw)
    assert len(parsed) == 1
    assert parsed[0].criterion == "c1"


# ── Overall verdict ────────────────────────────────────────────────


def test_overall_verdict_empty_is_warn():
    assert _overall_verdict([]) == "warn"


def test_overall_verdict_all_pass():
    crits = [
        CriterionVerdict(criterion="c1", **{"pass": True}),
        CriterionVerdict(criterion="c2", **{"pass": True}),
    ]
    assert _overall_verdict(crits) == "pass"


def test_overall_verdict_any_fail_is_fail():
    crits = [
        CriterionVerdict(criterion="c1", **{"pass": True}),
        CriterionVerdict(criterion="c2", **{"pass": False}),
    ]
    assert _overall_verdict(crits) == "fail"


def test_overall_verdict_all_fail_is_fail():
    crits = [
        CriterionVerdict(criterion="c1", **{"pass": False}),
        CriterionVerdict(criterion="c2", **{"pass": False}),
    ]
    assert _overall_verdict(crits) == "fail"


# ── Response model alias round-trip ────────────────────────────────


def test_criterion_verdict_serializes_pass_alias():
    c = CriterionVerdict(criterion="c1", **{"pass": True}, notes="ok")
    dumped = c.model_dump(by_alias=True)
    assert dumped == {"criterion": "c1", "pass": True, "notes": "ok"}


@pytest.mark.asyncio
async def test_review_handler_accepts_current_sandbox_service(monkeypatch):
    async def fake_call_ollama(prompt: str, model: str) -> str:
        assert "F-X-003" in prompt
        assert model == review_route.DEFAULT_MODEL
        return json.dumps(
            {"criteria": [{"criterion": "tests pass", "pass": True, "notes": "ok"}]}
        )

    logged = []

    async def fake_log_review(**kwargs):
        logged.append(kwargs)

    monkeypatch.setattr(review_route, "_call_ollama", fake_call_ollama)
    monkeypatch.setattr(review_route, "_log_review", fake_log_review)

    request = SimpleNamespace(
        state=SimpleNamespace(
            iss="sandbox",
            actor_type="service",
            scopes=["forge.llm.call"],
            user_id="sandbox",
        )
    )

    result = await review_route.review(
        ReviewRequest(
            spec_id="F-X-003",
            code_diff="diff --git a/x b/x",
            acceptance_criteria=["tests pass"],
        ),
        request,
    )

    assert result.overall_verdict == "pass"
    assert result.criteria[0].pass_ is True
    assert logged and logged[0]["status_code"] == 200
