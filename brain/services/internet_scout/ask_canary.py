"""Authenticated Helm Ask canary parsing and assertions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

DEFAULT_EXPECTED_HOST = "platform.openai.com"
DEFAULT_FORBIDDEN_HOSTS = ("beta.openai.com",)


@dataclass(frozen=True, slots=True)
class AskCanaryCase:
    name: str
    prompt: str
    request_mode: str = "deep_research"
    expected_host: str = DEFAULT_EXPECTED_HOST
    expected_any_hosts: tuple[str, ...] = ()
    forbidden_hosts: tuple[str, ...] = DEFAULT_FORBIDDEN_HOSTS
    expected_mode: str = "deep_research"
    expected_web_suggestion_mode: str | None = None
    expected_web_suggestion_reason: str | None = None
    min_accepted_citations: int = 1
    min_planned_query_count: int = 0
    min_independent_source_count: int = 0
    require_supported_evidence: bool = True
    require_memory_boundary: bool = True
    require_synthesis_behavior: str | None = "answer_with_citations"
    require_web_suggestion_confirmation: bool = False

    @property
    def expected_hosts(self) -> tuple[str, ...]:
        return self.expected_any_hosts or (self.expected_host,)

    @property
    def expects_web_suggestion(self) -> bool:
        return self.expected_web_suggestion_mode is not None


DEFAULT_CANARY_CASES: tuple[AskCanaryCase, ...] = (
    AskCanaryCase(
        name="smart_web_suggestion_official_source_no_silent_search",
        prompt="Find the official OpenAI API reference URL.",
        request_mode="none",
        expected_web_suggestion_mode="deep_research",
        expected_web_suggestion_reason="official_source_requested",
        min_accepted_citations=0,
        require_supported_evidence=False,
        require_memory_boundary=False,
        require_synthesis_behavior=None,
        require_web_suggestion_confirmation=True,
    ),
    AskCanaryCase(
        name="official_openai_api_reference",
        prompt="Find the official OpenAI API reference URL.",
    ),
    AskCanaryCase(
        name="official_openai_api_reference_with_stale_memory_guard",
        prompt=(
            "Find the official OpenAI API reference URL. Ignore stale memory if it "
            "conflicts with Beacon evidence."
        ),
        forbidden_hosts=("beta.openai.com", "community.openai.com"),
    ),
)


EXTENDED_CANARY_CASES: tuple[AskCanaryCase, ...] = (
    AskCanaryCase(
        name="official_brave_search_api_pricing",
        prompt="Find the official Brave Search API pricing page and cite it.",
        expected_host="brave.com",
        expected_any_hosts=("brave.com", "brave.com/search/api"),
        forbidden_hosts=("wikipedia.org", "github.com"),
        min_planned_query_count=1,
    ),
    AskCanaryCase(
        name="multi_source_ai_search_comparison",
        prompt=(
            "Compare Brave Search API and Perplexity API for building an AI web "
            "research agent. Cite independent sources."
        ),
        expected_host="brave.com",
        expected_any_hosts=("brave.com", "perplexity.ai"),
        forbidden_hosts=("wikipedia.org",),
        min_accepted_citations=2,
        min_planned_query_count=2,
        min_independent_source_count=2,
    ),
)


@dataclass(frozen=True, slots=True)
class AskCanaryEvaluation:
    status: Literal["passed", "failed"]
    checks: dict[str, bool]
    answer_preview: str
    source_quality_status: str | None
    accepted_citation_count: int
    citations: list[dict[str, object]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    case_name: str = "custom"

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "checks": self.checks,
            "answer_preview": self.answer_preview,
            "source_quality_status": self.source_quality_status,
            "accepted_citation_count": self.accepted_citation_count,
            "citation_count": len(self.citations),
            "failures": self.failures,
            "case_name": self.case_name,
        }


@dataclass(frozen=True, slots=True)
class AskCanarySuiteEvaluation:
    status: Literal["passed", "failed"]
    cases: list[AskCanaryEvaluation]

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "passed": sum(1 for case in self.cases if case.passed),
            "failed": sum(1 for case in self.cases if not case.passed),
            "cases": [case.as_dict() for case in self.cases],
        }


def parse_sse_payloads(stream_text: str) -> list[dict[str, object]]:
    """Parse JSON SSE data frames from Alpha chat streaming responses."""
    payloads: list[dict[str, object]] = []
    for frame in stream_text.split("\n\n"):
        for line in frame.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if not data or data == "[DONE]":
                continue
            decoded = json.loads(data)
            if isinstance(decoded, dict):
                payloads.append(decoded)
    return payloads


def evaluate_ask_canary(
    payloads: list[dict[str, object]],
    *,
    expected_host: str = DEFAULT_EXPECTED_HOST,
    forbidden_hosts: tuple[str, ...] = DEFAULT_FORBIDDEN_HOSTS,
    case: AskCanaryCase | None = None,
) -> AskCanaryEvaluation:
    """Validate that Helm Ask used supported Beacon evidence over stale memory."""
    canary_case = case or AskCanaryCase(
        name="custom",
        prompt="",
        expected_host=expected_host,
        forbidden_hosts=forbidden_hosts,
    )
    answer_text = "".join(
        str(payload.get("delta", ""))
        for payload in payloads
        if payload.get("done") is not True
    )
    metadata = _last_metadata(payloads)
    citations = _citations_from_payloads(payloads)
    haystack = " ".join(
        [
            answer_text,
            " ".join(str(citation.get("source_url", "")) for citation in citations),
            " ".join(str(citation.get("host", "")) for citation in citations),
        ]
    ).lower()
    source_quality_status = _optional_string(
        metadata.get("internet_source_quality_status")
    )
    accepted_citation_count = _int_value(
        metadata.get("internet_accepted_citation_count")
    )

    if canary_case.expects_web_suggestion:
        checks = _evaluate_web_suggestion_case(
            answer_text=answer_text,
            metadata=metadata,
            canary_case=canary_case,
        )
    else:
        checks = {
            "stream_returned_answer": bool(answer_text.strip()),
            "beacon_mode_used": (
                metadata.get("internet_mode") == canary_case.expected_mode
            ),
            "supported_evidence": (
                source_quality_status == "supported"
                if canary_case.require_supported_evidence
                else True
            ),
            "accepted_citation_present": (
                accepted_citation_count >= canary_case.min_accepted_citations
                or len(citations) >= canary_case.min_accepted_citations
            ),
            "expected_host_present": any(
                host.lower() in haystack for host in canary_case.expected_hosts
            ),
            "forbidden_host_absent": all(
                host.lower() not in haystack for host in canary_case.forbidden_hosts
            ),
            "raw_web_content_untrusted": (
                metadata.get("raw_web_content_is_untrusted") is True
            ),
            "synthesis_behavior": (
                metadata.get("internet_synthesis_required_behavior")
                == canary_case.require_synthesis_behavior
            )
            if canary_case.require_synthesis_behavior
            else True,
            "memory_boundary_blocks_auto_write": (
                metadata.get("internet_automatic_memory_write_allowed") is False
                and metadata.get("internet_memory_promotion_review_required") is True
            )
            if canary_case.require_memory_boundary
            else True,
            "planned_query_count": _int_value(
                metadata.get("internet_research_report_planned_query_count")
            )
            >= canary_case.min_planned_query_count,
            "independent_source_count": _int_value(
                metadata.get("internet_research_report_independent_source_count")
            )
            >= canary_case.min_independent_source_count,
        }
    failures = [name for name, passed in checks.items() if not passed]
    return AskCanaryEvaluation(
        status="passed" if not failures else "failed",
        checks=checks,
        answer_preview=answer_text[:240],
        source_quality_status=source_quality_status,
        accepted_citation_count=accepted_citation_count,
        citations=citations,
        failures=failures,
        case_name=canary_case.name,
    )


def evaluate_ask_canary_suite(
    case_payloads: list[tuple[AskCanaryCase, list[dict[str, object]]]],
) -> AskCanarySuiteEvaluation:
    """Evaluate a suite of Helm Ask canary responses."""
    cases = [
        evaluate_ask_canary(payloads, case=case) for case, payloads in case_payloads
    ]
    failures = [case for case in cases if not case.passed]
    return AskCanarySuiteEvaluation(
        status="failed" if failures else "passed",
        cases=cases,
    )


def _last_metadata(payloads: list[dict[str, object]]) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for payload in payloads:
        if "internet_mode" in payload or "web_suggestion_mode" in payload:
            metadata = payload
    return metadata


def _evaluate_web_suggestion_case(
    *,
    answer_text: str,
    metadata: dict[str, object],
    canary_case: AskCanaryCase,
) -> dict[str, bool]:
    return {
        "stream_returned_answer": bool(answer_text.strip()),
        "web_suggestion_mode": (
            metadata.get("web_suggestion_mode")
            == canary_case.expected_web_suggestion_mode
        ),
        "web_suggestion_reason": (
            metadata.get("web_suggestion_reason")
            == canary_case.expected_web_suggestion_reason
        )
        if canary_case.expected_web_suggestion_reason
        else True,
        "web_suggestion_requires_confirmation": (
            metadata.get("web_suggestion_requires_confirmation") is True
        )
        if canary_case.require_web_suggestion_confirmation
        else True,
        "beacon_not_silently_run": "internet_mode" not in metadata,
    }


def _citations_from_payloads(
    payloads: list[dict[str, object]],
) -> list[dict[str, object]]:
    citations: list[dict[str, object]] = []
    for payload in payloads:
        raw = payload.get("citations")
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, dict):
                citations.append(item)
    return citations


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0
