from __future__ import annotations

import json

from brain.services.internet_scout.ask_canary import (
    evaluate_ask_canary,
    parse_sse_payloads,
)


def test_ask_canary_passes_supported_official_evidence() -> None:
    stream = "\n\n".join(
        [
            'data: {"internet_mode":"deep_research",'
            '"internet_source_quality_status":"supported",'
            '"internet_accepted_citation_count":1,'
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
