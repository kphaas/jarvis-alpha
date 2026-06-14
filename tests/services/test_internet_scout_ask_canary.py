from __future__ import annotations

import json

from brain.services.internet_scout.ask_canary import (
    DEFAULT_CANARY_CASES,
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

    suite = evaluate_ask_canary_suite(
        [(case, supported_payloads) for case in DEFAULT_CANARY_CASES]
    )

    assert suite.passed is True
    assert suite.as_dict()["passed"] == len(DEFAULT_CANARY_CASES)
