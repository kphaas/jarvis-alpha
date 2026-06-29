from __future__ import annotations

import os

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://127.0.0.1:8188")

from brain.services.internet_scout.answer_engine_evals import (
    answer_engine_eval_payload,
    run_answer_engine_evals,
)
from brain.services.internet_scout.models import InternetScoutRequest, InternetTool
from brain.services.internet_scout.orchestrator import InternetScoutOrchestrator


def test_answer_engine_evals_all_pass() -> None:
    results = run_answer_engine_evals()

    assert len(results) >= 11
    assert all(result.passed for result in results)


def test_answer_engine_eval_payload_groups_contracts() -> None:
    payload = answer_engine_eval_payload()

    assert payload["status"] == "passed"
    assert payload["case_groups"]["focus_modes"]["case_count"] == 5
    assert payload["case_groups"]["citation_surface"]["case_count"] == 1
    assert payload["case_groups"]["refusal_quality"]["case_count"] == 1
    assert payload["case_groups"]["deep_research"]["case_count"] == 1
    assert payload["case_groups"]["evidence_transparency"]["case_count"] == 1


def test_focus_mode_is_part_of_research_plan_contract() -> None:
    plan = InternetScoutOrchestrator().plan(
        InternetScoutRequest(
            query="OpenAI API documentation",
            tool_hint=InternetTool.SEARCH,
            focus_mode="official",
            max_pages=2,
            requester="alpha_ui.beacon_answer_engine",
        )
    )

    assert plan.research.intent == "official_docs"
    assert plan.research.authority_required is True
    assert plan.research.provider_strategy == "fanout"
    assert "focus_mode:official" in plan.research.notes


def test_deep_research_eval_requires_complete_vendor_coverage() -> None:
    result = next(
        item
        for item in run_answer_engine_evals()
        if item.name == "deep_research_surfaces_plan_and_coverage"
    )

    assert result.passed is True
    assert (
        result.details["covered_official_target_count"]
        == result.details["required_official_target_count"]
    )
    assert len(result.details["research_report_verified_claims"]) >= 2
    assert result.details["research_report_unsupported_claims"] == []
    assert result.details["research_report_coverage_warnings"] == []
