"""Authenticated Helm Ask canary parsing and assertions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

DEFAULT_EXPECTED_HOST = "platform.openai.com"
DEFAULT_FORBIDDEN_HOSTS = ("beta.openai.com",)


@dataclass(frozen=True, slots=True)
class AskCanaryEvaluation:
    status: Literal["passed", "failed"]
    checks: dict[str, bool]
    answer_preview: str
    source_quality_status: str | None
    accepted_citation_count: int
    citations: list[dict[str, object]] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

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
) -> AskCanaryEvaluation:
    """Validate that Helm Ask used supported Beacon evidence over stale memory."""
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

    checks = {
        "stream_returned_answer": bool(answer_text.strip()),
        "beacon_mode_used": metadata.get("internet_mode") == "deep_research",
        "supported_evidence": source_quality_status == "supported",
        "accepted_citation_present": accepted_citation_count > 0 or len(citations) > 0,
        "expected_host_present": expected_host.lower() in haystack,
        "forbidden_host_absent": all(
            host.lower() not in haystack for host in forbidden_hosts
        ),
        "raw_web_content_untrusted": metadata.get("raw_web_content_is_untrusted")
        is True,
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
    )


def _last_metadata(payloads: list[dict[str, object]]) -> dict[str, object]:
    metadata: dict[str, object] = {}
    for payload in payloads:
        if "internet_mode" in payload:
            metadata = payload
    return metadata


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
