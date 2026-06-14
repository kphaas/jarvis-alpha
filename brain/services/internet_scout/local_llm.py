"""Local-LLM response adapter for Beacon evidence."""

from __future__ import annotations

from typing import Literal

from brain.services.internet_scout.models import (
    InternetScoutCitationQualitySummary,
    InternetScoutLocalLLMCitation,
    InternetScoutLocalLLMResponse,
    InternetScoutMemoryBoundary,
    InternetScoutResearchReport,
    InternetScoutSourceRanking,
    InternetScoutSynthesisContract,
    InternetScoutStoredResponse,
    SourceQualityLevel,
)
from brain.services.internet_scout.source_quality import evaluate_citation_quality

ReportAnswerability = Literal["answerable", "limited", "not_verified"]

_SOURCE_QUALITY_SCORE: dict[SourceQualityLevel, int] = {
    "official": 95,
    "primary": 85,
    "trusted_secondary": 72,
    "general": 55,
    "low_confidence": 25,
    "rejected": 0,
}
_CONFIDENCE_SCORE_ADJUSTMENT = {
    "high": 5,
    "medium": 0,
    "low": -8,
}


def build_local_llm_response(
    stored: InternetScoutStoredResponse,
) -> InternetScoutLocalLLMResponse:
    """Format Beacon evidence for a local model without granting page authority."""
    evaluation = evaluate_citation_quality(stored.evidence)
    citations = _rank_citations(evaluation.citations)
    synthesis = _synthesis_contract(
        citations=citations,
        quality=evaluation.summary,
    )
    memory_boundary = InternetScoutMemoryBoundary()
    research_report = _research_report(
        stored=stored,
        citations=citations,
        quality=evaluation.summary,
        synthesis=synthesis,
        memory_boundary=memory_boundary,
    )

    return InternetScoutLocalLLMResponse(
        request_id=stored.request_id,
        plan=stored.plan,
        evidence=stored.evidence,
        citations=citations,
        quality=evaluation.summary,
        synthesis=synthesis,
        memory_boundary=memory_boundary,
        research_report=research_report,
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


def _research_report(
    *,
    stored: InternetScoutStoredResponse,
    citations: list[InternetScoutLocalLLMCitation],
    quality: InternetScoutCitationQualitySummary,
    synthesis: InternetScoutSynthesisContract,
    memory_boundary: InternetScoutMemoryBoundary,
) -> InternetScoutResearchReport:
    query = (stored.evidence.request.query or "Beacon research").strip()
    answerability = _report_answerability(synthesis)
    source_hosts = list(dict.fromkeys(citation.host for citation in citations))
    source_rankings = _source_rankings(citations)
    findings = _report_findings(citations)
    limitations = [
        *synthesis.limitations[:5],
        *quality.warnings[:5],
    ][:10]
    summary = _report_summary(
        answerability=answerability,
        citation_count=len(citations),
        source_hosts=source_hosts,
    )
    report_markdown = _report_markdown(
        title=query,
        summary=summary,
        findings=findings,
        limitations=limitations,
        source_hosts=source_hosts,
        source_rankings=source_rankings,
        memory_boundary=memory_boundary,
    )
    return InternetScoutResearchReport(
        answerability=answerability,
        title=query[:200],
        summary=summary,
        key_findings=findings,
        limitations=limitations,
        cited_source_count=len(citations),
        source_hosts=source_hosts,
        source_rankings=source_rankings,
        report_markdown=report_markdown,
    )


def _report_answerability(
    synthesis: InternetScoutSynthesisContract,
) -> ReportAnswerability:
    if synthesis.required_behavior == "answer_with_citations":
        return "answerable"
    if synthesis.required_behavior == "answer_with_limitations":
        return "limited"
    return "not_verified"


def _report_findings(
    citations: list[InternetScoutLocalLLMCitation],
) -> list[str]:
    findings: list[str] = []
    for index, citation in enumerate(citations[:10], start=1):
        claim = citation.claim or citation.citation_text
        findings.append(f"[{index}] {claim[:500]}")
    return findings


def _report_summary(
    *,
    answerability: ReportAnswerability,
    citation_count: int,
    source_hosts: list[str],
) -> str:
    if answerability == "answerable":
        return (
            f"Beacon found {citation_count} accepted cited source(s) across "
            f"{len(source_hosts)} host(s)."
        )
    if answerability == "limited":
        return (
            f"Beacon found limited cited evidence from {citation_count} accepted "
            "source(s); answer with explicit limitations."
        )
    return "Beacon did not find acceptable cited evidence for a verified answer."


def _report_markdown(
    *,
    title: str,
    summary: str,
    findings: list[str],
    limitations: list[str],
    source_hosts: list[str],
    source_rankings: list[InternetScoutSourceRanking],
    memory_boundary: InternetScoutMemoryBoundary,
) -> str:
    lines = [
        f"# {title[:200]}",
        "",
        "## Summary",
        summary,
        "",
        "## Key Findings",
    ]
    lines.extend(f"- {finding}" for finding in findings[:10])
    if not findings:
        lines.append("- No accepted cited findings.")
    lines.extend(["", "## Limitations"])
    lines.extend(f"- {item}" for item in limitations[:10])
    if not limitations:
        lines.append("- No additional limitations beyond the cited evidence boundary.")
    lines.extend(["", "## Source Ranking"])
    lines.extend(
        (
            f"- [{source.rank}] {source.host} "
            f"({source.source_quality}, {source.confidence}, score {source.score})"
        )
        for source in source_rankings[:10]
    )
    if not source_rankings:
        lines.append("- No ranked accepted sources.")
    lines.extend(["", "## Sources"])
    lines.extend(f"- {host}" for host in source_hosts[:25])
    if not source_hosts:
        lines.append("- No accepted source hosts.")
    lines.extend(
        [
            "",
            "## Memory Boundary",
            f"- Automatic memory write allowed: {memory_boundary.automatic_memory_write_allowed}",
            f"- Promotion review required: {memory_boundary.promotion_review_required}",
            f"- Policy: {memory_boundary.policy}",
        ]
    )
    return "\n".join(lines)[:16000]


def _rank_citations(
    citations: list[InternetScoutLocalLLMCitation],
) -> list[InternetScoutLocalLLMCitation]:
    ranked: list[InternetScoutLocalLLMCitation] = []
    for rank, citation in enumerate(citations[:25], start=1):
        ranked.append(
            citation.model_copy(
                update={
                    "source_rank": rank,
                    "source_score": _source_score(citation),
                }
            )
        )
    return ranked


def _source_rankings(
    citations: list[InternetScoutLocalLLMCitation],
) -> list[InternetScoutSourceRanking]:
    rankings: list[InternetScoutSourceRanking] = []
    for citation in citations[:25]:
        if citation.source_rank is None:
            continue
        rankings.append(
            InternetScoutSourceRanking(
                rank=citation.source_rank,
                source_url=citation.source_url,
                host=citation.host,
                source_quality=citation.source_quality,
                confidence=citation.confidence,
                score=citation.source_score,
                reasons=_source_ranking_reasons(citation),
            )
        )
    return rankings


def _source_score(citation: InternetScoutLocalLLMCitation) -> int:
    score = _SOURCE_QUALITY_SCORE[citation.source_quality]
    score += _CONFIDENCE_SCORE_ADJUSTMENT[citation.confidence]
    return max(0, min(100, score))


def _source_ranking_reasons(citation: InternetScoutLocalLLMCitation) -> list[str]:
    reasons = [
        f"source_quality:{citation.source_quality}",
        f"confidence:{citation.confidence}",
    ]
    reasons.extend(citation.quality_reasons[:8])
    return reasons[:10]


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
                    f"Source rank: {citation.source_rank or index}",
                    f"Source score: {citation.source_score}",
                ]
            )
        )
    return "\n\n".join(parts)[:12000]
