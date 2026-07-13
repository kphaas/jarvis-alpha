"""Redacted chat trace corpus helpers for deterministic replay evals."""

from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from brain.privacy.redaction import redact_contact_tokens, short_hash, stable_hash

CHAT_REDACTED_TRACE_CORPUS_SCHEMA_VERSION = "chat_redacted_trace_corpus.v1"
CHAT_TRACE_REDACTION_POLICY_VERSION = "chat_trace_redaction.v1"
CHAT_TRACE_SAMPLING_WORKFLOW_VERSION = "chat_trace_sampling.v1"
CHAT_TRACE_SAMPLE_RETENTION_POLICY = "delete_raw_after_export"
CHAT_TRACE_APPROVAL_PUBLIC_KEY_PATH_ENV = (
    "ALPHA_CHAT_TRACE_APPROVAL_PUBLIC_KEY_PATH"
)
REDACTED_TRACE_CORPUS_PATH = Path("docs/evals/chat_redacted_trace_corpus.v1.json")
MAX_TRACE_SAMPLE_BATCH = 25
MAX_TRACE_TEXT_CHARS = 50_000
MAX_TRACE_APPROVAL_PUBLIC_KEY_BYTES = 16_384
REDACTED_TRACE_CORPUS_DESCRIPTION = (
    "Metadata-safe redacted chat replay cases. Do not store raw prompt, response, "
    "contact, identifier, or private memory text here."
)
_LEGACY_REDACTED_CASE_SHA256 = frozenset(
    {"sha256:961ed4e07bb1532485dbcbd79a44736fbb7b06d4fe30a5acd812e1f89ad06cf6"}
)

_TRACE_TEXT_FIELDS = (
    "prompt",
    "memory_context",
    "internet_context",
    "response_text",
    "expected_memory_present",
    "expected_memory_absent",
)
_TRACE_METADATA_FIELDS = (
    "name",
    "requested_model",
    "internet_mode",
    "expected_route_mode",
    "expected_quality_action",
    "expected_escalation",
    "expected_tool_policy",
    "expected_repair_action",
    "expected_repaired",
    "memory_budget_chars",
)
_REDACTED_CASE_FIELDS = frozenset(
    {
        "schema_version",
        "source",
        "trace_id",
        "redaction",
        *_TRACE_TEXT_FIELDS,
        *_TRACE_METADATA_FIELDS,
    }
)
_REDACTION_FIELDS = frozenset(
    {
        "policy_version",
        "source_trace_hash",
        "raw_trace_text_retained",
        "redacted_text_fields",
        "replacement_count",
    }
)
_CORPUS_FIELDS = frozenset(
    {
        "schema_version",
        "redaction_policy_version",
        "description",
        "sampling_workflow_version",
        "sampling_batches",
        "cases",
    }
)
_SAMPLE_PAYLOAD_FIELDS = frozenset({"schema_version", "approval", "candidates"})
_SAMPLE_APPROVAL_FIELDS = frozenset(
    {
        "status",
        "approval_ref",
        "purpose",
        "sensitive_terms_reviewed",
        "raw_source_retention",
    }
)
_SAMPLE_CANDIDATE_FIELDS = frozenset(
    {
        "source_trace_id",
        "prompt",
        "requested_model",
        "internet_mode",
        "memory_context",
        "internet_context",
        "response_text",
        "outcome",
        "sensitive_terms",
        "expected_memory_present",
        "expected_memory_absent",
    }
)
_SAMPLE_OUTCOME_FIELDS = frozenset(
    {
        "chat_outcome_schema_version",
        "chat_outcome_route_mode",
        "chat_outcome_quality_action",
        "chat_outcome_escalation_rung",
        "chat_repair_action",
        "chat_repair_repaired",
        "chat_memory_pack_budget_chars",
        "chat_prompt_tool_policy",
    }
)
_SAMPLING_BATCH_FIELDS = frozenset(
    {
        "workflow_version",
        "approval_ref",
        "approved_redacted_content_sha256",
        "approval_key_sha256",
        "approval_signature",
        "approval_status",
        "purpose",
        "sensitive_terms_reviewed",
        "raw_source_retention",
        "raw_trace_text_retained",
        "sampled_case_count",
        "source_trace_hashes",
    }
)
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_SAFE_REF_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,79}$")
_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:+-]{0,127}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SECRET_PATTERNS = (
    re.compile(
        r"\b(?:api[_ -]?key|password|secret|token)\s*[:=]\s*[^\s,;]{8,}",
        re.IGNORECASE,
    ),
    re.compile(r"\bbearer\s+[A-Za-z0-9._~+/-]{8,}", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.IGNORECASE),
    re.compile(
        r"\b(?:sk-(?:proj-|ant-[A-Za-z0-9-]*|svcacct-)?|pplx-|xai-|gsk_|hf_)"
        r"[A-Za-z0-9_-]{16,}\b"
    ),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(
        r"\b(?:ghp_|github_pat_|glpat-|xox[baprs]-|sk_live_)"
        r"[A-Za-z0-9_-]{16,}\b"
    ),
    re.compile(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
        r"[A-Za-z0-9_-]{8,}\b"
    ),
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
    raw_candidate = json.dumps(
        dict(candidate),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    redacted: dict[str, object] = {
        key: candidate[key] for key in _TRACE_METADATA_FIELDS if key in candidate
    }
    raw_trace_id = str(
        candidate.get("source_trace_id") or candidate.get("trace_id") or raw_candidate
    )
    redacted["trace_id"] = (
        f"redacted-trace-{short_hash(raw_trace_id, namespace='chat_trace')}"
    )
    redacted["source"] = "redacted_real_trace"
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
            raw_trace_id,
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
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        raise ValueError("redacted_trace_secret_leak")
    redacted = redact_contact_tokens(text, namespace="chat_trace")
    count = 0 if redacted == text else 1
    redacted, replacements = _UUID_RE.subn(
        lambda match: (
            f"[uuid:{stable_hash(match.group(0), namespace='chat_trace')[-12:]}]"
        ),
        redacted,
    )
    count += replacements
    redacted, replacements = _SSN_RE.subn(
        lambda match: (
            f"[ssn:{stable_hash(match.group(0), namespace='chat_trace')[-12:]}]"
        ),
        redacted,
    )
    count += replacements
    redacted, replacements = _IPV4_RE.subn(
        lambda match: (
            f"[ip:{stable_hash(match.group(0), namespace='chat_trace')[-12:]}]"
        ),
        redacted,
    )
    count += replacements
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
    *,
    approval_public_key_pem: bytes | None = None,
) -> list[RedactedTraceReplayCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    batches = payload.get("sampling_batches") if isinstance(payload, Mapping) else None
    if batches and approval_public_key_pem is None:
        key_path = os.getenv(CHAT_TRACE_APPROVAL_PUBLIC_KEY_PATH_ENV, "").strip()
        if not key_path:
            raise ValueError("redacted_trace_approval_public_key_required")
        approval_public_key_pem = load_trace_sample_approval_public_key(
            Path(key_path)
        )
    cases = validate_redacted_trace_corpus(
        payload,
        approval_public_key_pem=approval_public_key_pem,
    )
    return [_case_from_mapping(item) for item in cases]


def validate_redacted_trace_corpus(
    payload: Mapping[str, object],
    *,
    approval_public_key_pem: bytes | None = None,
) -> list[object]:
    _require_only_fields(
        payload,
        _CORPUS_FIELDS,
        "redacted_trace_corpus_fields_not_allowed",
    )
    if payload.get("schema_version") != CHAT_REDACTED_TRACE_CORPUS_SCHEMA_VERSION:
        raise ValueError("redacted_trace_corpus_schema_mismatch")
    if payload.get("redaction_policy_version") != CHAT_TRACE_REDACTION_POLICY_VERSION:
        raise ValueError("redacted_trace_corpus_policy_mismatch")
    if payload.get("description") != REDACTED_TRACE_CORPUS_DESCRIPTION:
        raise ValueError("redacted_trace_corpus_description_mismatch")
    workflow_version = payload.get("sampling_workflow_version")
    if workflow_version not in (None, CHAT_TRACE_SAMPLING_WORKFLOW_VERSION):
        raise ValueError("redacted_trace_sampling_workflow_mismatch")
    batches = payload.get("sampling_batches", [])
    if not isinstance(batches, list):
        raise ValueError("redacted_trace_sampling_batches_required")
    for batch in batches:
        _validate_sampling_batch(batch)
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("redacted_trace_corpus_cases_required")
    cases_by_hash: dict[str, Mapping[str, object]] = {}
    batch_reference_counts: dict[str, int] = {}
    for item in cases:
        if not isinstance(item, Mapping):
            raise ValueError("redacted_trace_case_object_required")
        validate_redacted_trace_case(item)
        source_hash = str(
            _mapping_value(item.get("redaction")).get("source_trace_hash")
        )
        if source_hash in cases_by_hash:
            raise ValueError("redacted_trace_source_hash_duplicate")
        cases_by_hash[source_hash] = item
    for batch in batches:
        batch_mapping = _mapping_value(batch)
        batch_hashes = batch_mapping.get("source_trace_hashes", [])
        if not isinstance(batch_hashes, list):
            raise ValueError("redacted_trace_sampling_batch_hashes_invalid")
        if any(str(value) not in cases_by_hash for value in batch_hashes):
            raise ValueError("redacted_trace_sampling_batch_case_missing")
        for value in batch_hashes:
            source_hash = str(value)
            batch_reference_counts[source_hash] = (
                batch_reference_counts.get(source_hash, 0) + 1
            )
        batch_cases = [cases_by_hash[str(value)] for value in batch_hashes]
        if batch_mapping.get(
            "approved_redacted_content_sha256"
        ) != _redacted_content_sha256(batch_cases):
            raise ValueError("redacted_trace_sampling_batch_digest_mismatch")
        if approval_public_key_pem is None:
            raise ValueError("redacted_trace_approval_public_key_required")
        _verify_trace_sample_approval_signature(
            approval_ref=_required_text(batch_mapping, "approval_ref"),
            redacted_content_sha256=_required_text(
                batch_mapping,
                "approved_redacted_content_sha256",
            ),
            approval_signature=_required_text(
                batch_mapping,
                "approval_signature",
            ),
            approval_public_key_pem=approval_public_key_pem,
            expected_key_sha256=_required_text(
                batch_mapping,
                "approval_key_sha256",
            ),
        )
    for source_hash, case in cases_by_hash.items():
        reference_count = batch_reference_counts.get(source_hash, 0)
        if reference_count > 1:
            raise ValueError("redacted_trace_sampling_case_multiple_batches")
        if (
            reference_count == 0
            and _legacy_redacted_case_sha256(case)
            not in _LEGACY_REDACTED_CASE_SHA256
        ):
            raise ValueError("redacted_trace_sampling_case_unsigned")
    return cases


def build_approved_trace_sample_corpus(
    sample_payload: Mapping[str, object],
    *,
    approval_ref: str,
    approved_redacted_content_sha256: str,
    approval_signature: str,
    approval_public_key_pem: bytes,
    existing_corpus: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Append an approved, redacted batch to a replay corpus."""
    review_artifact = prepare_trace_sample_review_artifact(sample_payload)
    _require_only_fields(
        sample_payload,
        _SAMPLE_PAYLOAD_FIELDS,
        "trace_sampling_payload_fields_not_allowed",
    )
    if sample_payload.get("schema_version") != CHAT_TRACE_SAMPLING_WORKFLOW_VERSION:
        raise ValueError("trace_sampling_schema_mismatch")
    approval = _mapping_value(sample_payload.get("approval"))
    redacted_content_sha256 = _required_text(
        review_artifact,
        "redacted_content_sha256",
    )
    approval_key_sha256 = _validate_sampling_approval(
        approval,
        approval_ref=approval_ref,
        approved_redacted_content_sha256=approved_redacted_content_sha256,
        redacted_content_sha256=redacted_content_sha256,
        approval_signature=approval_signature,
        approval_public_key_pem=approval_public_key_pem,
    )
    sampled_cases = _list_value(
        review_artifact.get("cases"),
        "trace_sampling_review_cases_required",
    )

    corpus = _corpus_for_append(
        existing_corpus,
        approval_public_key_pem=approval_public_key_pem,
    )
    cases = _list_value(corpus.get("cases"), "redacted_trace_corpus_cases_required")
    batches = _list_value(
        corpus.get("sampling_batches"),
        "redacted_trace_sampling_batches_required",
    )
    if any(
        isinstance(batch, Mapping) and batch.get("approval_ref") == approval_ref
        for batch in batches
    ):
        raise ValueError("trace_sampling_approval_ref_duplicate")
    source_hashes = {
        str(_mapping_value(case.get("redaction")).get("source_trace_hash"))
        for case in cases
        if isinstance(case, Mapping)
    }
    names = {str(case.get("name")) for case in cases if isinstance(case, Mapping)}
    sampled_hashes: list[str] = []
    for sampled in sampled_cases:
        if not isinstance(sampled, Mapping):
            raise ValueError("trace_sampling_review_case_object_required")
        source_hash = str(
            _mapping_value(sampled.get("redaction")).get("source_trace_hash")
        )
        if source_hash in source_hashes:
            raise ValueError("trace_sampling_source_duplicate")
        if str(sampled.get("name")) in names:
            raise ValueError("trace_sampling_case_name_duplicate")
        source_hashes.add(source_hash)
        names.add(str(sampled.get("name")))
        sampled_hashes.append(source_hash)
        cases.append(sampled)

    batches.append(
        {
            "workflow_version": CHAT_TRACE_SAMPLING_WORKFLOW_VERSION,
            "approval_ref": approval_ref,
            "approved_redacted_content_sha256": redacted_content_sha256,
            "approval_key_sha256": approval_key_sha256,
            "approval_signature": approval_signature,
            "approval_status": "approved",
            "purpose": "offline_quality_eval",
            "sensitive_terms_reviewed": True,
            "raw_source_retention": CHAT_TRACE_SAMPLE_RETENTION_POLICY,
            "raw_trace_text_retained": False,
            "sampled_case_count": len(sampled_hashes),
            "source_trace_hashes": sampled_hashes,
        }
    )
    corpus["cases"] = cases
    corpus["sampling_batches"] = batches
    validate_redacted_trace_corpus(
        corpus,
        approval_public_key_pem=approval_public_key_pem,
    )
    return corpus


def prepare_trace_sample_review_artifact(
    sample_payload: Mapping[str, object],
) -> dict[str, object]:
    """Create the exact redacted content that an operator must review."""
    _require_only_fields(
        sample_payload,
        _SAMPLE_PAYLOAD_FIELDS,
        "trace_sampling_payload_fields_not_allowed",
    )
    if sample_payload.get("schema_version") != CHAT_TRACE_SAMPLING_WORKFLOW_VERSION:
        raise ValueError("trace_sampling_schema_mismatch")
    candidates = sample_payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("trace_sampling_candidates_required")
    if len(candidates) > MAX_TRACE_SAMPLE_BATCH:
        raise ValueError("trace_sampling_batch_too_large")

    sampled_cases = [_sample_candidate(candidate) for candidate in candidates]
    source_hashes = [
        str(_mapping_value(case.get("redaction")).get("source_trace_hash"))
        for case in sampled_cases
    ]
    names = [str(case.get("name")) for case in sampled_cases]
    if len(set(source_hashes)) != len(source_hashes):
        raise ValueError("trace_sampling_source_duplicate")
    if len(set(names)) != len(names):
        raise ValueError("trace_sampling_case_name_duplicate")

    approval_ref = _required_string(
        _mapping_value(sample_payload.get("approval")),
        "approval_ref",
    )
    if not _SAFE_REF_RE.fullmatch(approval_ref):
        raise ValueError("trace_sampling_approval_ref_not_safe")
    redacted_content_sha256 = _redacted_content_sha256(sampled_cases)
    return {
        "workflow_version": CHAT_TRACE_SAMPLING_WORKFLOW_VERSION,
        "redaction_policy_version": CHAT_TRACE_REDACTION_POLICY_VERSION,
        "approval_ref": approval_ref,
        "approval_statement": trace_sample_approval_statement(
            approval_ref=approval_ref,
            redacted_content_sha256=redacted_content_sha256,
        ).decode("ascii"),
        "redacted_content_sha256": redacted_content_sha256,
        "sampled_case_count": len(sampled_cases),
        "cases": sampled_cases,
    }


def _redacted_content_sha256(cases: Sequence[Mapping[str, object]]) -> str:
    canonical = json.dumps(
        list(cases),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return stable_hash(canonical, namespace="chat_trace_review_content")


def _legacy_redacted_case_sha256(case: Mapping[str, object]) -> str:
    canonical = json.dumps(
        dict(case),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return stable_hash(canonical, namespace="chat_trace_legacy_case")


def trace_sample_approval_statement(
    *,
    approval_ref: str,
    redacted_content_sha256: str,
) -> bytes:
    """Return the canonical bytes signed by the independent approval key."""
    if not _SAFE_REF_RE.fullmatch(approval_ref):
        raise ValueError("trace_sampling_approval_ref_not_safe")
    if not _SHA256_RE.fullmatch(redacted_content_sha256):
        raise ValueError("trace_sampling_approved_digest_invalid")
    return (
        f"{CHAT_TRACE_SAMPLING_WORKFLOW_VERSION}\n"
        f"{approval_ref}\n"
        f"{redacted_content_sha256}\n"
    ).encode("ascii")


def load_trace_sample_approval_public_key(path: Path) -> bytes:
    """Read a bounded public key without exposing key contents in errors."""
    try:
        expanded = path.expanduser()
        if expanded.stat().st_size > MAX_TRACE_APPROVAL_PUBLIC_KEY_BYTES:
            raise ValueError("trace_sampling_approval_public_key_too_large")
        public_key_pem = expanded.read_bytes()
    except OSError as exc:
        raise ValueError("trace_sampling_approval_public_key_unreadable") from exc
    if not public_key_pem:
        raise ValueError("trace_sampling_approval_public_key_invalid")
    return public_key_pem


def _case_from_mapping(item: object) -> RedactedTraceReplayCase:
    if not isinstance(item, Mapping):
        raise ValueError("redacted_trace_case_object_required")
    validate_redacted_trace_case(item)
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


def validate_redacted_trace_case(item: Mapping[str, object]) -> None:
    _require_only_fields(
        item,
        _REDACTED_CASE_FIELDS,
        "redacted_trace_case_fields_not_allowed",
    )
    redaction = _mapping_value(item.get("redaction"))
    _require_only_fields(
        redaction,
        _REDACTION_FIELDS,
        "redacted_trace_redaction_fields_not_allowed",
    )
    if redaction.get("policy_version") != CHAT_TRACE_REDACTION_POLICY_VERSION:
        raise ValueError("redacted_trace_policy_mismatch")
    if redaction.get("raw_trace_text_retained") is not False:
        raise ValueError("redacted_trace_raw_text_retained")
    if not str(redaction.get("source_trace_hash") or "").startswith("sha256:"):
        raise ValueError("redacted_trace_source_hash_required")
    redacted_fields = redaction.get("redacted_text_fields")
    if not isinstance(redacted_fields, list) or set(redacted_fields) != set(
        _TRACE_TEXT_FIELDS
    ):
        raise ValueError("redacted_trace_text_fields_mismatch")
    rendered = json.dumps(dict(item), sort_keys=True)
    if redact_contact_tokens(rendered, namespace="chat_trace") != rendered:
        raise ValueError("redacted_trace_contact_token_leak")
    if _UUID_RE.search(rendered):
        raise ValueError("redacted_trace_uuid_leak")
    if _SSN_RE.search(rendered) or _IPV4_RE.search(rendered):
        raise ValueError("redacted_trace_identifier_leak")
    if any(pattern.search(rendered) for pattern in _SECRET_PATTERNS):
        raise ValueError("redacted_trace_secret_leak")
    if any(key.startswith("raw_") for key in item):
        raise ValueError("redacted_trace_raw_field_leak")
    if not _SAFE_REF_RE.fullmatch(_required_text(item, "name")):
        raise ValueError("redacted_trace_name_not_safe")
    if not _SAFE_REF_RE.fullmatch(_required_text(item, "trace_id")):
        raise ValueError("redacted_trace_id_not_safe")
    if item.get("source") != "redacted_real_trace":
        raise ValueError("redacted_trace_source_invalid")


def _sample_candidate(candidate: object) -> dict[str, object]:
    if not isinstance(candidate, Mapping):
        raise ValueError("trace_sampling_candidate_object_required")
    _require_only_fields(
        candidate,
        _SAMPLE_CANDIDATE_FIELDS,
        "trace_sampling_candidate_fields_not_allowed",
    )
    source_trace_id = _required_string(candidate, "source_trace_id")
    if len(source_trace_id) > 500:
        raise ValueError("trace_sampling_source_trace_id_too_large")
    for field in _TRACE_TEXT_FIELDS:
        value = candidate.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError("trace_sampling_text_type_invalid")
        if isinstance(value, str) and len(value) > MAX_TRACE_TEXT_CHARS:
            raise ValueError("trace_sampling_text_too_large")
    sensitive_terms = candidate.get("sensitive_terms")
    if not isinstance(sensitive_terms, list) or not sensitive_terms or any(
        not isinstance(term, str) or not term.strip() or len(term) > 200
        for term in sensitive_terms
    ):
        raise ValueError("trace_sampling_sensitive_terms_required")
    if len(sensitive_terms) > 64:
        raise ValueError("trace_sampling_sensitive_terms_too_many")
    outcome = _mapping_value(candidate.get("outcome"))
    _require_only_fields(
        outcome,
        _SAMPLE_OUTCOME_FIELDS,
        "trace_sampling_outcome_fields_not_allowed",
    )
    if outcome.get("chat_outcome_schema_version") != "chat_outcome.v1":
        raise ValueError("trace_sampling_outcome_schema_mismatch")
    quality_action = _required_safe_token(outcome, "chat_outcome_quality_action")
    escalation_value = outcome.get("chat_outcome_escalation_rung") or "none"
    escalation = _safe_token(
        escalation_value,
        error="trace_sampling_outcome_value_invalid",
    )
    if (quality_action == "accept") != (escalation == "none"):
        raise ValueError("trace_sampling_outcome_inconsistent")
    repaired = outcome.get("chat_repair_repaired", False)
    if not isinstance(repaired, bool):
        raise ValueError("trace_sampling_repair_repaired_invalid")
    budget = _bounded_int(
        outcome.get("chat_memory_pack_budget_chars") or 6000,
        minimum=1,
        maximum=MAX_TRACE_TEXT_CHARS,
        error="trace_sampling_memory_budget_invalid",
    )
    redacted = redact_chat_trace_candidate(
        {
            "name": (
                "sampled_real_trace_"
                f"{short_hash(source_trace_id, namespace='chat_trace_case')}"
            ),
            "source_trace_id": source_trace_id,
            "prompt": _required_string(candidate, "prompt"),
            "requested_model": _required_safe_token(candidate, "requested_model"),
            "internet_mode": _required_safe_token(candidate, "internet_mode"),
            "memory_context": str(candidate.get("memory_context") or ""),
            "internet_context": candidate.get("internet_context"),
            "response_text": _required_string(candidate, "response_text"),
            "expected_route_mode": _required_safe_token(
                outcome, "chat_outcome_route_mode"
            ),
            "expected_quality_action": quality_action,
            "expected_escalation": escalation,
            "expected_tool_policy": _required_safe_token(
                outcome, "chat_prompt_tool_policy"
            ),
            "expected_repair_action": _safe_token(
                outcome.get("chat_repair_action") or "none",
                error="trace_sampling_outcome_value_invalid",
            ),
            "expected_repaired": repaired,
            "memory_budget_chars": budget,
            "expected_memory_present": candidate.get("expected_memory_present"),
            "expected_memory_absent": candidate.get("expected_memory_absent"),
        },
        sensitive_terms=tuple(sensitive_terms),
    )
    replacement_count = _mapping_value(redacted.get("redaction")).get(
        "replacement_count"
    )
    if not isinstance(replacement_count, int) or replacement_count < 1:
        raise ValueError("trace_sampling_redaction_required")
    validate_redacted_trace_case(redacted)
    return redacted


def _validate_sampling_approval(
    approval: Mapping[str, object],
    *,
    approval_ref: str,
    approved_redacted_content_sha256: str,
    redacted_content_sha256: str,
    approval_signature: str,
    approval_public_key_pem: bytes,
) -> str:
    _require_only_fields(
        approval,
        _SAMPLE_APPROVAL_FIELDS,
        "trace_sampling_approval_fields_not_allowed",
    )
    if not _SAFE_REF_RE.fullmatch(approval_ref):
        raise ValueError("trace_sampling_approval_ref_not_safe")
    if approval.get("status") != "approved":
        raise ValueError("trace_sampling_approval_required")
    if approval.get("approval_ref") != approval_ref:
        raise ValueError("trace_sampling_approval_ref_mismatch")
    if approval.get("purpose") != "offline_quality_eval":
        raise ValueError("trace_sampling_purpose_not_allowed")
    if approval.get("sensitive_terms_reviewed") is not True:
        raise ValueError("trace_sampling_sensitive_terms_review_required")
    if approval.get("raw_source_retention") != CHAT_TRACE_SAMPLE_RETENTION_POLICY:
        raise ValueError("trace_sampling_retention_policy_required")
    if not _SHA256_RE.fullmatch(approved_redacted_content_sha256):
        raise ValueError("trace_sampling_approved_digest_invalid")
    if approved_redacted_content_sha256 != redacted_content_sha256:
        raise ValueError("trace_sampling_approved_digest_mismatch")
    return _verify_trace_sample_approval_signature(
        approval_ref=approval_ref,
        redacted_content_sha256=redacted_content_sha256,
        approval_signature=approval_signature,
        approval_public_key_pem=approval_public_key_pem,
    )


def _verify_trace_sample_approval_signature(
    *,
    approval_ref: str,
    redacted_content_sha256: str,
    approval_signature: str,
    approval_public_key_pem: bytes,
    expected_key_sha256: str | None = None,
) -> str:
    if len(approval_public_key_pem) > MAX_TRACE_APPROVAL_PUBLIC_KEY_BYTES:
        raise ValueError("trace_sampling_approval_public_key_too_large")
    if not isinstance(approval_signature, str) or not 1 <= len(approval_signature) <= 256:
        raise ValueError("trace_sampling_approval_signature_invalid")
    try:
        public_key = serialization.load_pem_public_key(approval_public_key_pem)
    except (TypeError, ValueError) as exc:
        raise ValueError("trace_sampling_approval_public_key_invalid") from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValueError("trace_sampling_approval_public_key_invalid")
    key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_sha256 = stable_hash(key_bytes, namespace="chat_trace_approval_key")
    if expected_key_sha256 is not None and expected_key_sha256 != key_sha256:
        raise ValueError("trace_sampling_approval_key_mismatch")
    try:
        signature = base64.b64decode(approval_signature, validate=True)
        public_key.verify(
            signature,
            trace_sample_approval_statement(
                approval_ref=approval_ref,
                redacted_content_sha256=redacted_content_sha256,
            ),
        )
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("trace_sampling_approval_signature_invalid") from exc
    return key_sha256


def _corpus_for_append(
    existing_corpus: Mapping[str, object] | None,
    *,
    approval_public_key_pem: bytes,
) -> dict[str, object]:
    if existing_corpus is None:
        return {
            "schema_version": CHAT_REDACTED_TRACE_CORPUS_SCHEMA_VERSION,
            "redaction_policy_version": CHAT_TRACE_REDACTION_POLICY_VERSION,
            "description": REDACTED_TRACE_CORPUS_DESCRIPTION,
            "sampling_workflow_version": CHAT_TRACE_SAMPLING_WORKFLOW_VERSION,
            "sampling_batches": [],
            "cases": [],
        }
    validate_redacted_trace_corpus(
        existing_corpus,
        approval_public_key_pem=approval_public_key_pem,
    )
    return {
        "schema_version": CHAT_REDACTED_TRACE_CORPUS_SCHEMA_VERSION,
        "redaction_policy_version": CHAT_TRACE_REDACTION_POLICY_VERSION,
        "description": REDACTED_TRACE_CORPUS_DESCRIPTION,
        "sampling_workflow_version": CHAT_TRACE_SAMPLING_WORKFLOW_VERSION,
        "sampling_batches": _list_value(
            existing_corpus.get("sampling_batches", []),
            "redacted_trace_sampling_batches_required",
        ),
        "cases": _list_value(
            existing_corpus.get("cases", []),
            "redacted_trace_corpus_cases_required",
        ),
    }


def _validate_sampling_batch(batch: object) -> None:
    if not isinstance(batch, Mapping):
        raise ValueError("redacted_trace_sampling_batch_object_required")
    _require_only_fields(
        batch,
        _SAMPLING_BATCH_FIELDS,
        "redacted_trace_sampling_batch_fields_not_allowed",
    )
    if batch.get("workflow_version") != CHAT_TRACE_SAMPLING_WORKFLOW_VERSION:
        raise ValueError("redacted_trace_sampling_batch_version_mismatch")
    if batch.get("approval_status") != "approved":
        raise ValueError("redacted_trace_sampling_batch_not_approved")
    if not _SAFE_REF_RE.fullmatch(str(batch.get("approval_ref") or "")):
        raise ValueError("redacted_trace_sampling_batch_approval_ref_not_safe")
    if not _SHA256_RE.fullmatch(
        str(batch.get("approved_redacted_content_sha256") or "")
    ):
        raise ValueError("redacted_trace_sampling_batch_digest_invalid")
    if not _SHA256_RE.fullmatch(str(batch.get("approval_key_sha256") or "")):
        raise ValueError("redacted_trace_sampling_batch_key_digest_invalid")
    signature = batch.get("approval_signature")
    if not isinstance(signature, str) or len(signature) > 256:
        raise ValueError("redacted_trace_sampling_batch_signature_invalid")
    if batch.get("purpose") != "offline_quality_eval":
        raise ValueError("redacted_trace_sampling_batch_purpose_mismatch")
    if batch.get("sensitive_terms_reviewed") is not True:
        raise ValueError("redacted_trace_sampling_batch_terms_not_reviewed")
    if batch.get("raw_source_retention") != CHAT_TRACE_SAMPLE_RETENTION_POLICY:
        raise ValueError("redacted_trace_sampling_batch_retention_mismatch")
    if batch.get("raw_trace_text_retained") is not False:
        raise ValueError("redacted_trace_sampling_batch_raw_text_retained")
    count = _bounded_int(
        batch.get("sampled_case_count"),
        minimum=1,
        maximum=MAX_TRACE_SAMPLE_BATCH,
        error="redacted_trace_sampling_batch_count_invalid",
    )
    hashes = batch.get("source_trace_hashes")
    if (
        not isinstance(hashes, list)
        or len(hashes) != count
        or any(not str(value).startswith("sha256:") for value in hashes)
    ):
        raise ValueError("redacted_trace_sampling_batch_hashes_invalid")
    if len(set(hashes)) != len(hashes):
        raise ValueError("redacted_trace_sampling_batch_hash_duplicate")


def _require_only_fields(
    payload: Mapping[str, object],
    allowed: frozenset[str],
    error: str,
) -> None:
    if set(payload) - allowed:
        raise ValueError(error)


def _bounded_int(
    value: object,
    *,
    minimum: int,
    maximum: int,
    error: str,
) -> int:
    if not isinstance(value, (int, float, str)) or isinstance(value, bool):
        raise ValueError(error)
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(error)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(error) from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(error)
    return parsed


def _list_value(value: object, error: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(error)
    return list(value)


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"trace_sampling_{key}_required")
    return value.strip()


def _required_safe_token(payload: Mapping[str, object], key: str) -> str:
    return _safe_token(
        payload.get(key),
        error=f"trace_sampling_{key}_invalid",
    )


def _safe_token(value: object, *, error: str) -> str:
    if not isinstance(value, str) or not _SAFE_TOKEN_RE.fullmatch(value):
        raise ValueError(error)
    return value


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"redacted_trace_{key}_required")
    return value


def _mapping_value(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}
