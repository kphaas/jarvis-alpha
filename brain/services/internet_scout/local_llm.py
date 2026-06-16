"""Local-LLM response adapter for Beacon evidence."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from brain.services.internet_scout.models import (
    InternetScoutCitationQualitySummary,
    InternetScoutLocalLLMCitation,
    InternetScoutLocalLLMResponse,
    InternetScoutMemoryBoundary,
    InternetScoutResearchReport,
    InternetScoutResearchStopCriteria,
    InternetScoutSourceRanking,
    InternetScoutSynthesisContract,
    InternetScoutStoredResponse,
    SourceQualityLevel,
)
from brain.services.internet_scout.source_quality import (
    CitationQualityEvaluation,
    evaluate_citation_quality,
)

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
        stop_criteria=stored.plan.research.stop_criteria,
    )
    memory_boundary = InternetScoutMemoryBoundary()
    research_report = _research_report(
        stored=stored,
        citations=citations,
        evaluation=evaluation,
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
        answer_context=_answer_context(citations, query=stored.evidence.request.query),
    )


def _synthesis_contract(
    *,
    citations: list[InternetScoutLocalLLMCitation],
    quality: InternetScoutCitationQualitySummary,
    stop_criteria: InternetScoutResearchStopCriteria,
) -> InternetScoutSynthesisContract:
    citation_count = len(citations)
    source_hosts = _citation_source_hosts(citations)
    stop_warnings = _stop_criteria_warnings(
        quality=quality,
        source_hosts=source_hosts,
        accepted_count=citation_count,
        stop_criteria=stop_criteria,
        contradiction_count=0,
    )
    minimum_citations_met = (
        quality.status == "supported"
        and citation_count >= stop_criteria.min_accepted_citations
    )
    if quality.status == "supported" and not stop_warnings:
        return InternetScoutSynthesisContract(
            answerable=True,
            status=quality.status,
            citation_count=citation_count,
            minimum_citations_met=minimum_citations_met,
            required_behavior="answer_with_citations",
            limitations=quality.warnings[:10],
        )
    if quality.status == "supported":
        return InternetScoutSynthesisContract(
            answerable=True,
            status="weak",
            citation_count=citation_count,
            minimum_citations_met=minimum_citations_met,
            required_behavior="answer_with_limitations",
            limitations=[
                *quality.warnings[:5],
                *stop_warnings[:4],
                "State that Beacon did not meet all research coverage criteria.",
            ][:10],
        )
    if quality.status == "weak":
        return InternetScoutSynthesisContract(
            answerable=True,
            status=quality.status,
            citation_count=citation_count,
            minimum_citations_met=minimum_citations_met,
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
    evaluation: CitationQualityEvaluation,
    quality: InternetScoutCitationQualitySummary,
    synthesis: InternetScoutSynthesisContract,
    memory_boundary: InternetScoutMemoryBoundary,
) -> InternetScoutResearchReport:
    query = (stored.evidence.request.query or "Beacon research").strip()
    plan = stored.plan.research
    source_hosts = _citation_source_hosts(citations)
    independent_source_count = len(source_hosts)
    source_diversity_score = _source_diversity_score(
        source_hosts=source_hosts,
        accepted_count=len(citations),
        stop_criteria=plan.stop_criteria,
    )
    source_rankings = _source_rankings(citations)
    findings = _report_findings(citations)
    verified_claims = _verified_claims(citations)
    unsupported_claims = _unsupported_claims(evaluation)
    contradictions = _contradictions(evaluation)
    coverage_warnings = _coverage_warnings(
        quality=quality,
        source_hosts=source_hosts,
        accepted_count=len(citations),
        stop_criteria=plan.stop_criteria,
        contradiction_count=len(contradictions),
    )
    stop_criteria_warnings = _stop_criteria_warnings(
        quality=quality,
        source_hosts=source_hosts,
        accepted_count=len(citations),
        stop_criteria=plan.stop_criteria,
        contradiction_count=len(contradictions),
    )
    answerability = _report_answerability(synthesis)
    if stop_criteria_warnings and answerability == "answerable":
        answerability = "limited"
    limitations = [
        *synthesis.limitations[:5],
        *quality.warnings[:5],
        *coverage_warnings[:5],
    ][:10]
    summary = _report_summary(
        answerability=answerability,
        citation_count=len(citations),
        source_hosts=source_hosts,
        verified_claim_count=quality.verified_claim_count,
        unsupported_claim_count=quality.unsupported_claim_count,
        source_diversity_score=source_diversity_score,
    )
    report_markdown = _report_markdown(
        title=query,
        summary=summary,
        findings=findings,
        limitations=limitations,
        source_hosts=source_hosts,
        source_rankings=source_rankings,
        independent_source_count=independent_source_count,
        source_diversity_score=source_diversity_score,
        plan_id=plan.plan_id,
        research_intent=plan.intent,
        planned_query_count=len(plan.searches),
        expected_source_types=plan.expected_source_types,
        stop_criteria=plan.stop_criteria.stop_when,
        verified_claims=verified_claims,
        unsupported_claims=unsupported_claims,
        contradictions=contradictions,
        coverage_warnings=coverage_warnings,
        memory_boundary=memory_boundary,
    )
    return InternetScoutResearchReport(
        answerability=answerability,
        plan_id=plan.plan_id or None,
        research_intent=plan.intent,
        source_quality_status=synthesis.status,
        title=query[:200],
        summary=summary,
        key_findings=findings,
        limitations=limitations,
        cited_source_count=len(citations),
        accepted_citation_count=quality.accepted_citation_count,
        rejected_citation_count=quality.rejected_citation_count,
        verified_claim_count=quality.verified_claim_count,
        unsupported_claim_count=quality.unsupported_claim_count,
        source_hosts=source_hosts,
        independent_source_count=independent_source_count,
        source_diversity_score=source_diversity_score,
        required_source_hosts=quality.required_source_hosts,
        expected_source_types=plan.expected_source_types,
        subquestion_count=len(plan.subquestions),
        planned_query_count=len(plan.searches),
        stop_criteria=plan.stop_criteria,
        verified_claims=verified_claims,
        unsupported_claims=unsupported_claims,
        contradiction_count=len(contradictions),
        contradictions=contradictions,
        coverage_warnings=coverage_warnings,
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
    verified_claim_count: int,
    unsupported_claim_count: int,
    source_diversity_score: int,
) -> str:
    if answerability == "answerable":
        return (
            f"Beacon found {citation_count} accepted cited source(s) across "
            f"{len(source_hosts)} host(s), with {verified_claim_count} verified "
            f"claim(s), {unsupported_claim_count} unsupported claim(s), and a "
            f"source diversity score of {source_diversity_score}."
        )
    if answerability == "limited":
        return (
            f"Beacon found limited cited evidence from {citation_count} accepted "
            f"source(s), with {verified_claim_count} verified claim(s) and "
            f"{unsupported_claim_count} unsupported claim(s); answer with explicit "
            "limitations."
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
    independent_source_count: int,
    source_diversity_score: int,
    plan_id: str,
    research_intent: str,
    planned_query_count: int,
    expected_source_types: Sequence[str],
    stop_criteria: Sequence[str],
    verified_claims: list[str],
    unsupported_claims: list[str],
    contradictions: list[str],
    coverage_warnings: list[str],
    memory_boundary: InternetScoutMemoryBoundary,
) -> str:
    lines = [
        f"# {title[:200]}",
        "",
        "## Research Plan",
        f"- Plan id: {plan_id or 'n/a'}",
        f"- Intent: {research_intent}",
        f"- Planned query count: {planned_query_count}",
        "- Expected source types: "
        f"{', '.join(expected_source_types) if expected_source_types else 'n/a'}",
        f"- Stop criteria: {'; '.join(stop_criteria) if stop_criteria else 'n/a'}",
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
    lines.extend(["", "## Claim Verification"])
    lines.extend(f"- Verified: {claim}" for claim in verified_claims[:10])
    if not verified_claims:
        lines.append("- Verified: none")
    lines.extend(f"- Unsupported: {claim}" for claim in unsupported_claims[:10])
    if not unsupported_claims:
        lines.append("- Unsupported: none")
    lines.extend(["", "## Contradictions"])
    lines.extend(f"- {claim}" for claim in contradictions[:10])
    if not contradictions:
        lines.append("- None detected")
    if coverage_warnings:
        lines.extend(["", "## Coverage Warnings"])
        lines.extend(f"- {warning}" for warning in coverage_warnings[:10])
    lines.extend(
        [
            "",
            "## Source Diversity",
            f"- Independent source hosts: {independent_source_count}",
            f"- Source diversity score: {source_diversity_score}",
        ]
    )
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


def _verified_claims(
    citations: list[InternetScoutLocalLLMCitation],
) -> list[str]:
    claims: list[str] = []
    for citation in citations[:10]:
        if citation.claim:
            claims.append(citation.claim[:500])
    return claims


def _unsupported_claims(
    evaluation: CitationQualityEvaluation,
) -> list[str]:
    claims: list[str] = []
    for item in evaluation.evaluated:
        if not item.unsupported_claim or not item.citation.claim:
            continue
        claims.append(item.citation.claim[:500])
        if len(claims) >= 10:
            break
    return claims


def _contradictions(
    evaluation: CitationQualityEvaluation,
) -> list[str]:
    claims: list[str] = []
    for item in evaluation.evaluated:
        if not item.citation.claim:
            continue
        if "claim_support:negation_mismatch" not in item.citation.quality_reasons:
            continue
        claims.append(item.citation.claim[:500])
        if len(claims) >= 10:
            break
    return claims


def _coverage_warnings(
    *,
    quality: InternetScoutCitationQualitySummary,
    source_hosts: list[str],
    accepted_count: int,
    stop_criteria: InternetScoutResearchStopCriteria,
    contradiction_count: int,
) -> list[str]:
    warnings = list(quality.warnings[:10])
    warnings.extend(
        _stop_criteria_warnings(
            quality=quality,
            source_hosts=source_hosts,
            accepted_count=accepted_count,
            stop_criteria=stop_criteria,
            contradiction_count=contradiction_count,
        )
    )
    return list(dict.fromkeys(warnings))[:20]


def _stop_criteria_warnings(
    *,
    quality: InternetScoutCitationQualitySummary,
    source_hosts: list[str],
    accepted_count: int,
    stop_criteria: InternetScoutResearchStopCriteria,
    contradiction_count: int,
) -> list[str]:
    warnings: list[str] = []
    if accepted_count < stop_criteria.min_accepted_citations:
        warnings.append("Accepted citations are below the research stop criteria.")
    if stop_criteria.require_official_source and quality.official_source_count == 0:
        warnings.append("Required official source evidence was not accepted.")
    if stop_criteria.require_cross_check and len(source_hosts) < 2:
        warnings.append("Cross-check coverage is below the research stop criteria.")
    if len(source_hosts) < stop_criteria.min_source_hosts:
        warnings.append("Source diversity is below the research stop criteria.")
    if quality.unsupported_claim_count:
        warnings.append("Unsupported claims violate the research stop criteria.")
    if contradiction_count:
        warnings.append("Potential contradictory claim evidence was detected.")
    return list(dict.fromkeys(warnings))[:20]


def _citation_source_hosts(citations: list[InternetScoutLocalLLMCitation]) -> list[str]:
    return list(dict.fromkeys(citation.host for citation in citations if citation.host))


def _source_diversity_score(
    *,
    source_hosts: list[str],
    accepted_count: int,
    stop_criteria: InternetScoutResearchStopCriteria,
) -> int:
    if not source_hosts or not accepted_count:
        return 0
    required_hosts = max(1, stop_criteria.min_source_hosts)
    host_score = min(70, round((len(source_hosts) / required_hosts) * 70))
    citation_score = min(30, accepted_count * 10)
    return max(0, min(100, host_score + citation_score))


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


def _answer_context(
    citations: list[InternetScoutLocalLLMCitation],
    *,
    query: str | None = None,
) -> str:
    parts: list[str] = []
    source_url_guidance = _source_url_answer_guidance(citations, query=query)
    if source_url_guidance:
        parts.append(source_url_guidance)
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


def _source_url_answer_guidance(
    citations: list[InternetScoutLocalLLMCitation],
    *,
    query: str | None,
) -> str:
    if not citations or not _query_requests_source_url(query):
        return ""
    preferred = citations[0].source_url
    source_lines = [
        f"- [{index}] {citation.source_url}"
        for index, citation in enumerate(citations[:5], start=1)
    ]
    return "\n".join(
        [
            "Answer target: source URL",
            (
                "The user asked for an official documentation/source URL. "
                "Use the cited Source URL as the answer."
            ),
            f"Preferred answer URL: {preferred} [1]",
            (
                "Do not answer with API endpoint URLs, request paths, or examples "
                "found in citation text unless the user explicitly asks for an API endpoint."
            ),
            "Cited source URLs:",
            *source_lines,
        ]
    )


def _query_requests_source_url(query: str | None) -> bool:
    normalized = f" {(query or '').lower()} "
    source_url_markers = (
        " url",
        " link",
        " documentation",
        " docs",
        " api reference",
        " reference url",
        " reference page",
        " official source",
    )
    endpoint_markers = (
        " endpoint",
        " base url",
        " request url",
        " /v1/",
        " curl ",
    )
    return any(marker in normalized for marker in source_url_markers) and not any(
        marker in normalized for marker in endpoint_markers
    )
