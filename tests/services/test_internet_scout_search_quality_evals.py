from __future__ import annotations

import os

os.environ.setdefault("ALPHA_DB_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_WRITER", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_DB_DSN_BUDDY", "postgresql://test:test@localhost/test")
os.environ.setdefault("ALPHA_GATEWAY_URL", "http://127.0.0.1:8188")

from brain.services.internet_scout.search_quality_evals import (
    run_search_quality_evals,
)


def test_search_quality_evals_all_pass() -> None:
    results = run_search_quality_evals()

    assert results
    assert all(result.passed for result in results)


def test_search_quality_evals_cover_core_quality_gates() -> None:
    results = {result.name: result for result in run_search_quality_evals()}

    official = results["official_openai_source_beats_community"]
    assert official.details["status"] == "supported"
    assert official.details["accepted_hosts"] == ["platform.openai.com"]
    assert official.details["official_source_count"] == 1
    assert official.details["research_plan_id"]
    assert official.details["research_provider_strategy"] == "fanout"
    assert official.details["research_search_providers"] == ["brave", "perplexity"]
    assert official.details["research_max_extracts"] == 4
    assert official.details["research_expected_source_types"] == [
        "official_docs",
        "primary_source",
    ]
    assert official.details["research_subquestion_count"] >= 2
    assert official.details["research_stop_criteria"]["require_official_source"] is True
    assert official.details["synthesis_required_behavior"] == "answer_with_citations"
    assert (
        official.details["research_report_plan_id"]
        == official.details["research_plan_id"]
    )
    assert official.details["research_report_answerability"] == "answerable"
    assert official.details["research_report_verified_claims"] == [
        "The OpenAI API reference is on platform.openai.com."
    ]
    assert official.details["automatic_memory_write_allowed"] is False
    assert official.details["memory_promotion_review_required"] is True

    unsupported = results["unsupported_official_pricing_claim_fails_closed"]
    assert unsupported.details["status"] == "insufficient"
    assert unsupported.details["unsupported_claim_count"] == 1
    assert unsupported.details["synthesis_answerable"] is False
    assert unsupported.details["research_report_answerability"] == "not_verified"
    assert unsupported.details["research_report_unsupported_claims"] == [
        "OpenAI charges $123 per request."
    ]

    injection = results["prompt_injection_marker_rejects_citation"]
    assert injection.details["status"] == "insufficient"
    assert injection.details["prompt_injection_rejection_count"] == 1

    current = results["current_fact_report_carries_plan_and_freshness_coverage"]
    assert current.details["status"] == "supported"
    assert "release_notes" in current.details["research_expected_source_types"]
    assert current.details["research_report_answerability"] == "answerable"

    comparison = results["comparison_plan_requires_cross_check_and_two_sources"]
    assert comparison.details["status"] == "supported"
    assert comparison.details["research_stop_criteria"]["require_cross_check"] is True
    assert comparison.details["accepted_hosts"] == ["brave.com", "perplexity.ai"]

    negated = results["negated_claim_mismatch_fails_closed"]
    assert negated.details["status"] == "insufficient"
    assert negated.details["unsupported_claim_count"] == 1
