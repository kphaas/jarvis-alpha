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
    assert official.details["research_provider_strategy"] == "fanout"
    assert official.details["research_search_providers"] == ["brave", "perplexity"]
    assert official.details["research_max_extracts"] == 4
    assert official.details["synthesis_required_behavior"] == "answer_with_citations"

    unsupported = results["unsupported_official_pricing_claim_fails_closed"]
    assert unsupported.details["status"] == "insufficient"
    assert unsupported.details["unsupported_claim_count"] == 1
    assert unsupported.details["synthesis_answerable"] is False

    injection = results["prompt_injection_marker_rejects_citation"]
    assert injection.details["status"] == "insufficient"
    assert injection.details["prompt_injection_rejection_count"] == 1
