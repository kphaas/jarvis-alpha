from __future__ import annotations

import json

from brain.services.internet_scout.ask_canary import (
    DEFAULT_CANARY_CASES,
    EXTENDED_CANARY_CASES,
    AskCanaryCase,
    evaluate_ask_canary,
    evaluate_ask_canary_suite,
    parse_sse_payloads,
)


def test_ask_canary_passes_supported_official_evidence() -> None:
    stream = "\n\n".join(
        [
            'data: {"internet_mode":"deep_research",'
            '"internet_source_quality_status":"supported",'
            '"internet_accepted_citation_count":1,'
            '"internet_synthesis_required_behavior":"answer_with_citations",'
            '"internet_automatic_memory_write_allowed":false,'
            '"internet_memory_promotion_review_required":true,'
            '"raw_web_content_is_untrusted":true,'
            '"citations":[{"source_url":"https://platform.openai.com/docs/api-reference",'
            '"host":"platform.openai.com"}]}',
            'data: {"delta":"Use https://platform.openai.com/docs/api-reference"}',
            'data: {"done":true}',
        ]
    )

    payloads = parse_sse_payloads(stream)
    evaluation = evaluate_ask_canary(payloads)

    assert evaluation.passed is True
    assert evaluation.failures == []


def test_ask_canary_rejects_stale_memory_host() -> None:
    payloads = [
        {
            "internet_mode": "deep_research",
            "internet_source_quality_status": "supported",
            "internet_accepted_citation_count": 1,
            "internet_synthesis_required_behavior": "answer_with_citations",
            "internet_automatic_memory_write_allowed": False,
            "internet_memory_promotion_review_required": True,
            "raw_web_content_is_untrusted": True,
            "citations": [
                {
                    "source_url": "https://platform.openai.com/docs/api-reference",
                    "host": "platform.openai.com",
                }
            ],
        },
        {
            "delta": "Use https://beta.openai.com/docs/api-reference from memory.",
        },
    ]

    evaluation = evaluate_ask_canary(payloads)

    assert evaluation.passed is False
    assert "forbidden_host_absent" in evaluation.failures
    assert json.dumps(evaluation.as_dict())


def test_ask_canary_rejects_missing_memory_boundary() -> None:
    payloads = [
        {
            "internet_mode": "deep_research",
            "internet_source_quality_status": "supported",
            "internet_accepted_citation_count": 1,
            "internet_synthesis_required_behavior": "answer_with_citations",
            "raw_web_content_is_untrusted": True,
            "citations": [
                {
                    "source_url": "https://platform.openai.com/docs/api-reference",
                    "host": "platform.openai.com",
                }
            ],
        },
        {"delta": "Use https://platform.openai.com/docs/api-reference"},
    ]

    evaluation = evaluate_ask_canary(payloads)

    assert evaluation.passed is False
    assert "memory_boundary_blocks_auto_write" in evaluation.failures


def test_ask_canary_passes_web_suggestion_without_silent_beacon() -> None:
    payloads = [
        {
            "web_suggestion_mode": "deep_research",
            "web_suggestion_reason": "official_source_requested",
            "web_suggestion_confidence": "high",
            "web_suggestion_query": "Find the official OpenAI API reference URL.",
            "web_suggestion_requires_confirmation": True,
            "web_suggestion_source": "alpha_smart_web_suggestion",
        },
        {"delta": "I can answer generally, but current evidence may help."},
    ]
    case = AskCanaryCase(
        name="suggestion",
        prompt="Find the official OpenAI API reference URL.",
        request_mode="none",
        expected_web_suggestion_mode="deep_research",
        expected_web_suggestion_reason="official_source_requested",
        min_accepted_citations=0,
        require_supported_evidence=False,
        require_memory_boundary=False,
        require_synthesis_behavior=None,
        require_web_suggestion_confirmation=True,
    )

    evaluation = evaluate_ask_canary(payloads, case=case)

    assert evaluation.passed is True
    assert evaluation.checks["beacon_not_silently_run"] is True


def test_ask_canary_rejects_silent_beacon_for_web_suggestion_case() -> None:
    payloads = [
        {
            "web_suggestion_mode": "deep_research",
            "web_suggestion_reason": "official_source_requested",
            "web_suggestion_requires_confirmation": True,
        },
        {
            "internet_mode": "deep_research",
            "internet_source_quality_status": "supported",
            "internet_accepted_citation_count": 1,
        },
        {"delta": "Use https://platform.openai.com/docs/api-reference"},
    ]
    case = AskCanaryCase(
        name="suggestion",
        prompt="Find the official OpenAI API reference URL.",
        request_mode="none",
        expected_web_suggestion_mode="deep_research",
        expected_web_suggestion_reason="official_source_requested",
        min_accepted_citations=0,
        require_supported_evidence=False,
        require_memory_boundary=False,
        require_synthesis_behavior=None,
        require_web_suggestion_confirmation=True,
    )

    evaluation = evaluate_ask_canary(payloads, case=case)

    assert evaluation.passed is False
    assert "beacon_not_silently_run" in evaluation.failures


def test_ask_canary_accepts_host_alias_and_research_report_minimums() -> None:
    payloads = [
        {
            "internet_mode": "deep_research",
            "internet_source_quality_status": "supported",
            "internet_accepted_citation_count": 2,
            "internet_synthesis_required_behavior": "answer_with_citations",
            "internet_automatic_memory_write_allowed": False,
            "internet_memory_promotion_review_required": True,
            "internet_research_report_planned_query_count": 2,
            "internet_research_report_independent_source_count": 2,
            "raw_web_content_is_untrusted": True,
            "citations": [
                {
                    "source_url": "https://docs.brave.com/search/api/",
                    "host": "docs.brave.com",
                },
                {
                    "source_url": "https://docs.perplexity.ai/",
                    "host": "docs.perplexity.ai",
                },
            ],
        },
        {"delta": "Use https://docs.brave.com/search/api/."},
    ]
    case = AskCanaryCase(
        name="multi_source",
        prompt="Compare Brave Search API and Perplexity API.",
        expected_any_hosts=("brave.com", "perplexity.ai"),
        min_accepted_citations=2,
        min_planned_query_count=2,
        min_independent_source_count=2,
    )

    evaluation = evaluate_ask_canary(payloads, case=case)

    assert evaluation.passed is True
    assert evaluation.checks["planned_query_count"] is True
    assert evaluation.checks["independent_source_count"] is True


def test_ask_canary_suite_aggregates_case_results() -> None:
    supported_payloads = [
        {
            "internet_mode": "deep_research",
            "internet_source_quality_status": "supported",
            "internet_accepted_citation_count": 1,
            "internet_synthesis_required_behavior": "answer_with_citations",
            "internet_automatic_memory_write_allowed": False,
            "internet_memory_promotion_review_required": True,
            "raw_web_content_is_untrusted": True,
            "citations": [
                {
                    "source_url": "https://platform.openai.com/docs/api-reference",
                    "host": "platform.openai.com",
                }
            ],
        },
        {"delta": "Use https://platform.openai.com/docs/api-reference"},
    ]
    suggestion_payloads = [
        {
            "web_suggestion_mode": "deep_research",
            "web_suggestion_reason": "official_source_requested",
            "web_suggestion_requires_confirmation": True,
        },
        {"delta": "I can answer generally, but current evidence may help."},
    ]
    case_payloads = [
        (
            case,
            suggestion_payloads if case.expects_web_suggestion else supported_payloads,
        )
        for case in DEFAULT_CANARY_CASES
    ]

    suite = evaluate_ask_canary_suite(case_payloads)

    assert suite.passed is True
    assert suite.as_dict()["passed"] == len(DEFAULT_CANARY_CASES)


def test_extended_canary_cases_stay_out_of_default_suite() -> None:
    default_names = {case.name for case in DEFAULT_CANARY_CASES}
    extended_names = {case.name for case in EXTENDED_CANARY_CASES}

    assert default_names.isdisjoint(extended_names)
    assert any(case.min_independent_source_count > 0 for case in EXTENDED_CANARY_CASES)
