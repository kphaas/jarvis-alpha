"""Redacted chat trace corpus helpers for deterministic replay evals."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from brain.privacy.redaction import redact_contact_tokens, stable_hash

CHAT_REDACTED_TRACE_CORPUS_SCHEMA_VERSION = "chat_redacted_trace_corpus.v1"
CHAT_TRACE_REDACTION_POLICY_VERSION = "chat_trace_redaction.v1"
REDACTED_TRACE_CORPUS_PATH = Path("docs/evals/chat_redacted_trace_corpus.v1.json")

_TRACE_TEXT_FIELDS = (
    "prompt",
    "memory_context",
    "internet_context",
    "response_text",
)
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


@dataclass(frozen=True, slots=True)
class RedactedTraceReplayCase:
    name: str
    trace_id: str
    prompt: str
    requested_model: str
    internet_mode: str
    memory_context: str
    internet_context: str | None
    response_text: str
    expected_route_mode: str
    expected_quality_action: str
    expected_escalation: str
    expected_tool_policy: str
    source_trace_hash: str
    redaction_policy_version: str
    expected_repair_action: str = "none"
    expected_repaired: bool = False
    memory_budget_chars: int = 6000
    expected_memory_present: str | None = None
    expected_memory_absent: str | None = None


def redact_chat_trace_candidate(
    candidate: Mapping[str, object],
    *,
    sensitive_terms: Sequence[str] = (),
) -> dict[str, object]:
    """Build a replayable trace case without retaining raw candidate text."""
    raw_text = "\n".join(
        str(candidate.get(field) or "") for field in _TRACE_TEXT_FIELDS
    )
    redacted: dict[str, object] = {
        key: value
        for key, value in candidate.items()
        if key not in _TRACE_TEXT_FIELDS and not key.startswith("raw_")
    }
    replacement_count = 0
    for field in _TRACE_TEXT_FIELDS:
        value = candidate.get(field)
        if value is None:
            redacted[field] = None
            continue
        text, count = redact_chat_trace_text(
            str(value), sensitive_terms=sensitive_terms
        )
        redacted[field] = text
        replacement_count += count

    redacted["schema_version"] = CHAT_REDACTED_TRACE_CORPUS_SCHEMA_VERSION
    redacted["redaction"] = {
        "policy_version": CHAT_TRACE_REDACTION_POLICY_VERSION,
        "source_trace_hash": stable_hash(
            raw_text,
            namespace="chat_redacted_trace",
        ),
        "raw_trace_text_retained": False,
        "redacted_text_fields": list(_TRACE_TEXT_FIELDS),
        "replacement_count": replacement_count,
    }
    return redacted


def redact_chat_trace_text(
    text: str,
    *,
    sensitive_terms: Sequence[str] = (),
) -> tuple[str, int]:
    redacted = redact_contact_tokens(text, namespace="chat_trace")
    count = 0 if redacted == text else 1
    redacted = _UUID_RE.sub(
        lambda match: (
            f"[uuid:{stable_hash(match.group(0), namespace='chat_trace')[-12:]}]"
        ),
        redacted,
    )
    for term in sensitive_terms:
        clean = term.strip()
        if not clean:
            continue
        pattern = re.compile(re.escape(clean), re.IGNORECASE)
        redacted, replacements = pattern.subn(
            f"[term:{stable_hash(clean.casefold(), namespace='chat_trace')[-12:]}]",
            redacted,
        )
        count += replacements
    return redacted, count


def load_redacted_trace_corpus(
    path: Path = REDACTED_TRACE_CORPUS_PATH,
) -> list[RedactedTraceReplayCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != CHAT_REDACTED_TRACE_CORPUS_SCHEMA_VERSION:
        raise ValueError("redacted_trace_corpus_schema_mismatch")
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("redacted_trace_corpus_cases_required")
    return [_case_from_mapping(item) for item in cases]


def _case_from_mapping(item: object) -> RedactedTraceReplayCase:
    if not isinstance(item, Mapping):
        raise ValueError("redacted_trace_case_object_required")
    _validate_redacted_case(item)
    redaction = _mapping_value(item.get("redaction"))
    return RedactedTraceReplayCase(
        name=_required_text(item, "name"),
        trace_id=_required_text(item, "trace_id"),
        prompt=_required_text(item, "prompt"),
        requested_model=_required_text(item, "requested_model"),
        internet_mode=_required_text(item, "internet_mode"),
        memory_context=str(item.get("memory_context") or ""),
        internet_context=(
            str(item["internet_context"]) if item.get("internet_context") else None
        ),
        response_text=_required_text(item, "response_text"),
        expected_route_mode=_required_text(item, "expected_route_mode"),
        expected_quality_action=_required_text(item, "expected_quality_action"),
        expected_escalation=_required_text(item, "expected_escalation"),
        expected_tool_policy=_required_text(item, "expected_tool_policy"),
        source_trace_hash=_required_text(redaction, "source_trace_hash"),
        redaction_policy_version=_required_text(redaction, "policy_version"),
        expected_repair_action=str(item.get("expected_repair_action") or "none"),
        expected_repaired=bool(item.get("expected_repaired") or False),
        memory_budget_chars=int(item.get("memory_budget_chars") or 6000),
        expected_memory_present=(
            str(item["expected_memory_present"])
            if item.get("expected_memory_present")
            else None
        ),
        expected_memory_absent=(
            str(item["expected_memory_absent"])
            if item.get("expected_memory_absent")
            else None
        ),
    )


def _validate_redacted_case(item: Mapping[str, object]) -> None:
    redaction = _mapping_value(item.get("redaction"))
    if redaction.get("policy_version") != CHAT_TRACE_REDACTION_POLICY_VERSION:
        raise ValueError("redacted_trace_policy_mismatch")
    if redaction.get("raw_trace_text_retained") is not False:
        raise ValueError("redacted_trace_raw_text_retained")
    if not str(redaction.get("source_trace_hash") or "").startswith("sha256:"):
        raise ValueError("redacted_trace_source_hash_required")
    rendered = json.dumps(
        {field: item.get(field) for field in _TRACE_TEXT_FIELDS},
        sort_keys=True,
    )
    if redact_contact_tokens(rendered, namespace="chat_trace") != rendered:
        raise ValueError("redacted_trace_contact_token_leak")
    if any(key.startswith("raw_") for key in item):
        raise ValueError("redacted_trace_raw_field_leak")


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"redacted_trace_{key}_required")
    return value


def _mapping_value(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}
