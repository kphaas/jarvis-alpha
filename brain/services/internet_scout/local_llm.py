"""Local-LLM response adapter for Beacon evidence."""

from __future__ import annotations

from brain.services.internet_scout.models import (
    InternetScoutCitationQualitySummary,
    InternetScoutLocalLLMCitation,
    InternetScoutLocalLLMResponse,
    InternetScoutSynthesisContract,
    InternetScoutStoredResponse,
)
from brain.services.internet_scout.source_quality import evaluate_citation_quality


def build_local_llm_response(
    stored: InternetScoutStoredResponse,
) -> InternetScoutLocalLLMResponse:
    """Format Beacon evidence for a local model without granting page authority."""
    evaluation = evaluate_citation_quality(stored.evidence)
    citations = evaluation.citations

    return InternetScoutLocalLLMResponse(
        request_id=stored.request_id,
        plan=stored.plan,
        evidence=stored.evidence,
        citations=citations,
        quality=evaluation.summary,
        synthesis=_synthesis_contract(
            citations=citations,
            quality=evaluation.summary,
        ),
        answer_context=_answer_context(citations),
    )


def _synthesis_contract(
    *,
    citations: list[InternetScoutLocalLLMCitation],
    quality: InternetScoutCitationQualitySummary,
) -> InternetScoutSynthesisContract:
    citation_count = len(citations)
    if quality.status == "supported":
        return InternetScoutSynthesisContract(
            answerable=True,
            status=quality.status,
            citation_count=citation_count,
            minimum_citations_met=True,
            required_behavior="answer_with_citations",
            limitations=quality.warnings[:10],
        )
    if quality.status == "weak":
        return InternetScoutSynthesisContract(
            answerable=True,
            status=quality.status,
            citation_count=citation_count,
            minimum_citations_met=False,
            required_behavior="answer_with_limitations",
            limitations=[
                *quality.warnings[:9],
                "State that Beacon found limited corroborating evidence.",
            ][:10],
        )
    return InternetScoutSynthesisContract(
        answerable=False,
        status=quality.status,
        citation_count=citation_count,
        minimum_citations_met=False,
        required_behavior="state_not_verified",
        limitations=[
            *quality.warnings[:9],
            "State that Beacon did not find acceptable source evidence.",
        ][:10],
    )


def _answer_context(citations: list[InternetScoutLocalLLMCitation]) -> str:
    parts: list[str] = []
    for index, citation in enumerate(citations, start=1):
        parts.append(
            "\n".join(
                [
                    f"Claim: {citation.claim}" if citation.claim else "Claim: n/a",
                    f"[{index}] {citation.citation_text}",
                    f"Source: {citation.source_url}",
                    f"Host: {citation.host}",
                    f"Content hash: {citation.content_hash}",
                    f"Confidence: {citation.confidence}",
                    f"Source quality: {citation.source_quality}",
                ]
            )
        )
    return "\n\n".join(parts)[:12000]
