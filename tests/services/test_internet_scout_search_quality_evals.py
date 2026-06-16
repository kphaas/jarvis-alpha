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

    assert len(results) >= 30
    assert len(results) <= 50
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

    responses_docs = results["openai_responses_docs_url_prefers_source_url"]
    responses_answer_context = str(responses_docs.details["answer_context"])
    assert responses_docs.details["status"] == "supported"
    assert responses_docs.details["accepted_hosts"] == ["platform.openai.com"]
    assert responses_docs.details["official_source_count"] == 1
    assert "Answer target: source URL" in responses_answer_context
    assert (
        "Preferred answer URL: https://platform.openai.com/docs/api-reference/responses [1]"
        in responses_answer_context
    )
    assert responses_answer_context.index(
        "https://platform.openai.com/docs/api-reference/responses"
    ) < responses_answer_context.index("https://api.openai.com/v1/responses/resp_123")

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
    assert comparison.eval_group == "daily_use"
    assert comparison.details["research_stop_criteria"]["require_cross_check"] is True
    assert comparison.details["accepted_hosts"] == ["brave.com", "perplexity.ai"]

    # Official vendor comparisons should retain the vendor docs host in coverage.
    official_vendor_comparison = results[
        "official_vendor_comparison_prefers_provider_docs"
    ]
    assert official_vendor_comparison.details["status"] == "supported"
    assert official_vendor_comparison.eval_group == "daily_use"
    assert official_vendor_comparison.details["official_source_count"] == 2
    assert official_vendor_comparison.details["accepted_hosts"] == [
        "brave.com",
        "docs.perplexity.ai",
    ]
    assert official_vendor_comparison.details["research_intent"] == "comparison"
    assert official_vendor_comparison.details["required_official_target_count"] == 2
    assert official_vendor_comparison.details["covered_official_target_count"] == 2
    assert (
        official_vendor_comparison.details["research_stop_criteria"][
            "require_cross_check"
        ]
        is True
    )
    assert official_vendor_comparison.details["synthesis_required_behavior"] == (
        "answer_with_citations"
    )
    assert official_vendor_comparison.details["research_expected_source_types"] == [
        "official_docs",
        "primary_source",
        "trusted_secondary",
    ]
    assert official_vendor_comparison.details["research_query_purposes"] == [
        "baseline",
        "comparison",
        "comparison",
        "cross_check",
    ]

    official_openai_anthropic = results[
        "official_openai_anthropic_comparison_requires_both_vendor_docs"
    ]
    assert official_openai_anthropic.details["status"] == "supported"
    assert sorted(official_openai_anthropic.details["accepted_hosts"]) == [
        "docs.anthropic.com",
        "platform.openai.com",
    ]
    assert official_openai_anthropic.details["required_official_target_count"] == 2
    assert official_openai_anthropic.details["covered_official_target_count"] == 2

    official_openai_anthropic_gap = results[
        "official_openai_anthropic_comparison_downgrades_when_vendor_missing"
    ]
    assert official_openai_anthropic_gap.details["status"] == "weak"
    assert official_openai_anthropic_gap.details["accepted_hosts"] == [
        "platform.openai.com"
    ]
    assert official_openai_anthropic_gap.details["required_official_target_count"] == 2
    assert official_openai_anthropic_gap.details["covered_official_target_count"] == 1
    assert official_openai_anthropic_gap.details["synthesis_required_behavior"] == (
        "answer_with_limitations"
    )
    assert (
        "Official comparison coverage is missing for one or more compared targets."
        in official_openai_anthropic_gap.details["research_report_coverage_warnings"]
    )

    non_ai_comparison = results[
        "non_ai_serverless_comparison_requires_independent_sources"
    ]
    assert non_ai_comparison.details["status"] == "supported"
    assert non_ai_comparison.eval_group == "daily_use"
    assert non_ai_comparison.details["research_intent"] == "comparison"
    assert (
        non_ai_comparison.details["research_stop_criteria"]["require_cross_check"]
        is True
    )
    assert non_ai_comparison.details["accepted_hosts"] == [
        "developers.cloudflare.com",
        "docs.aws.amazon.com",
    ]

    official_cloudflare_aws = results[
        "official_cloudflare_aws_comparison_requires_both_vendor_docs"
    ]
    assert official_cloudflare_aws.details["status"] == "supported"
    assert official_cloudflare_aws.details["required_official_target_count"] == 2
    assert official_cloudflare_aws.details["covered_official_target_count"] == 2

    official_cloudflare_aws_gap = results[
        "official_cloudflare_aws_comparison_downgrades_when_vendor_missing"
    ]
    assert official_cloudflare_aws_gap.details["status"] == "weak"
    assert official_cloudflare_aws_gap.details["accepted_hosts"] == [
        "developers.cloudflare.com"
    ]
    assert official_cloudflare_aws_gap.details["required_official_target_count"] == 2
    assert official_cloudflare_aws_gap.details["covered_official_target_count"] == 1
    assert official_cloudflare_aws_gap.details["synthesis_required_behavior"] == (
        "answer_with_limitations"
    )

    negated = results["negated_claim_mismatch_fails_closed"]
    assert negated.details["status"] == "insufficient"
    assert negated.details["unsupported_claim_count"] == 1

    claim_gap = results["number_mismatch_rejects_limit_claim"]
    assert claim_gap.details["status"] == "insufficient"
    assert claim_gap.details["unsupported_claim_count"] == 1

    source_gap = results["reddit_rejected_for_official_openai_query"]
    assert source_gap.details["status"] == "insufficient"
    assert source_gap.details["rejected_citation_count"] == 1
