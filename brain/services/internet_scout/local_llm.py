"""Local-LLM response adapter for Beacon evidence."""

from __future__ import annotations

from brain.services.internet_scout.models import (
    InternetScoutLocalLLMCitation,
    InternetScoutLocalLLMResponse,
    InternetScoutStoredResponse,
)


def build_local_llm_response(
    stored: InternetScoutStoredResponse,
) -> InternetScoutLocalLLMResponse:
    """Format Beacon evidence for a local model without granting page authority."""
    source_by_url = {source.url: source for source in stored.evidence.sources}
    citations: list[InternetScoutLocalLLMCitation] = []
    for claim in stored.evidence.claims[:25]:
        source = source_by_url.get(claim.source_url)
        if source is None:
            continue
        citations.append(
            InternetScoutLocalLLMCitation(
                source_url=source.url,
                host=source.host,
                content_hash=source.content_hash,
                citation_text=claim.citation_text,
                confidence=claim.confidence,
            )
        )

    return InternetScoutLocalLLMResponse(
        request_id=stored.request_id,
        plan=stored.plan,
        evidence=stored.evidence,
        citations=citations,
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
                ]
            )
        )
    return "\n\n".join(parts)[:12000]
