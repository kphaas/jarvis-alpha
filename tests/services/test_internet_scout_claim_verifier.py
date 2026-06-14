from __future__ import annotations

from brain.services.internet_scout.claim_verifier import verify_claim_support


def test_verify_claim_support_rejects_negation_mismatch() -> None:
    result = verify_claim_support(
        claim="The Beacon browser runtime is available for this request.",
        citation_text="The Beacon browser runtime is not available for this request.",
    )

    assert result.supported is False
    assert result.reasons == ("negation_mismatch",)


def test_verify_claim_support_rejects_version_mismatch() -> None:
    result = verify_claim_support(
        claim="The latest SDK version is v4.2.1.",
        citation_text="The latest SDK version is v4.1.9.",
    )

    assert result.supported is False
    assert result.reasons == ("version_missing",)


def test_verify_claim_support_rejects_date_marker_mismatch() -> None:
    result = verify_claim_support(
        claim="The report was updated in June 2026.",
        citation_text="The report was updated in May 2026.",
    )

    assert result.supported is False
    assert result.reasons == ("date_marker_missing",)


def test_verify_claim_support_rejects_unit_mismatch() -> None:
    result = verify_claim_support(
        claim="The documented timeout is 30 seconds.",
        citation_text="The documented timeout is 30 minutes.",
    )

    assert result.supported is False
    assert result.reasons == ("unit_marker_missing",)


def test_verify_claim_support_accepts_supported_negated_claim() -> None:
    result = verify_claim_support(
        claim="The endpoint is not available without approval.",
        citation_text="The endpoint is not available without approval.",
    )

    assert result.supported is True
    assert result.reasons == ("text_substring_match",)
