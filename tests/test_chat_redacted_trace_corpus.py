from __future__ import annotations

import json
from dataclasses import asdict

from brain.services.chat_redacted_trace_corpus import (
    CHAT_TRACE_REDACTION_POLICY_VERSION,
    load_redacted_trace_corpus,
    redact_chat_trace_candidate,
)


def test_redacts_chat_trace_candidate_without_raw_sensitive_text() -> None:
    redacted = redact_chat_trace_candidate(
        {
            "name": "raw_candidate",
            "trace_id": "11111111-2222-3333-4444-555555555555",
            "prompt": "Ken Haas asked from ken@example.com about docs.",
            "requested_model": "auto",
            "internet_mode": "web_search",
            "memory_context": "Ken Haas remembered beta.openai.com.",
            "internet_context": "Official source: platform.openai.com/docs",
            "response_text": "Call 404-555-1212. Use platform.openai.com/docs.",
            "expected_route_mode": "perplexity",
            "expected_quality_action": "accept",
            "expected_escalation": "none",
            "expected_tool_policy": "beacon_evidence_is_authority",
            "raw_transcript": "must not survive",
        },
        sensitive_terms=("Ken Haas",),
    )
    rendered = json.dumps(redacted)

    assert redacted["redaction"]["policy_version"] == (
        CHAT_TRACE_REDACTION_POLICY_VERSION
    )
    assert redacted["redaction"]["raw_trace_text_retained"] is False
    assert redacted["redaction"]["source_trace_hash"].startswith("sha256:")
    assert "raw_transcript" not in redacted
    assert "Ken Haas" not in rendered
    assert "ken@example.com" not in rendered
    assert "404-555-1212" not in rendered
    assert "[term:" in rendered
    assert "[email:" in rendered
    assert "[phone:" in rendered


def test_committed_redacted_trace_corpus_loads_without_raw_contact_leaks() -> None:
    cases = load_redacted_trace_corpus()
    rendered = json.dumps([asdict(case) for case in cases])

    assert len(cases) == 1
    assert cases[0].redaction_policy_version == CHAT_TRACE_REDACTION_POLICY_VERSION
    assert cases[0].source_trace_hash.startswith("sha256:")
    assert "ken@example.com" not in rendered
    assert "404-555-1212" not in rendered
    assert "Ken Haas" not in rendered
