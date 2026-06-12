"""Local-LLM response adapter for Beacon evidence."""

from __future__ import annotations

from brain.services.internet_scout.models import (
    InternetScoutLocalLLMCitation,
    InternetScoutLocalLLMResponse,
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
        answer_context=_answer_context(citations),
    )


def _answer_context(citations: list[InternetScoutLocalLLMCitation]) -> str:
    parts: list[str] = []
    for index, citation in enumerate(citations, start=1):
        parts.append(
            "\n".join(
                [
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
