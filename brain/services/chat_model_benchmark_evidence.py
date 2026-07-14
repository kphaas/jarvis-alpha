"""Approved, metadata-only evidence for chat model benchmark comparisons."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from datetime import datetime
import json
import re
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from brain.privacy.redaction import stable_hash
from brain.routing.model_capability_registry import (
    CHAT_MODEL_CAPABILITY_REGISTRY_VERSION,
    DEFAULT_CHAT_MODEL_CAPABILITIES,
    get_chat_model_capability,
)
from brain.services.chat_model_task_benchmarks import (
    CHAT_MODEL_TASK_BENCHMARK_SCHEMA_VERSION,
    CHAT_MODEL_TASK_BENCHMARK_VERSION,
    DEFAULT_CHAT_MODEL_BENCHMARK_TASKS,
    ChatModelBenchmarkTask,
    ChatModelTaskBenchmarkResult,
    chat_model_task_benchmark_payload,
)

CHAT_MODEL_BENCHMARK_EVIDENCE_SCHEMA_VERSION = "chat_model_benchmark_evidence.v1"
CHAT_MODEL_BENCHMARK_APPROVAL_VERSION = "chat_model_benchmark_approval.v1"
CHAT_MODEL_BENCHMARK_COMPARISON_VERSION = "chat_model_benchmark_comparison.v1"
CHAT_MODEL_BENCHMARK_EVIDENCE_PATH_ENV = "ALPHA_CHAT_MODEL_BENCHMARK_EVIDENCE_PATH"
CHAT_MODEL_BENCHMARK_APPROVAL_KEY_PATH_ENV = (
    "ALPHA_CHAT_MODEL_BENCHMARK_APPROVAL_PUBLIC_KEY_PATH"
)
MAX_BENCHMARK_EVIDENCE_BATCHES = 100
MAX_APPROVAL_PUBLIC_KEY_BYTES = 16_384

_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}")
_SAFE_APPROVAL_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}")
_RAW_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_TOP_LEVEL_FIELDS = frozenset(
    {
        "schema_version",
        "benchmark_version",
        "registry_version",
        "run_completed_at",
        "status",
        "advisory_only",
        "routing_scores_mutated",
        "passed",
        "failed",
        "scorecards",
        "results",
        "reporting",
    }
)
_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "benchmark_version",
        "registry_version",
        "task_id",
        "task_class",
        "route_mode",
        "provider",
        "model_id",
        "deployment",
        "privacy_tier",
        "cost_tier",
        "registry_task_score",
        "score",
        "minimum_score",
        "passed",
        "latency_ms",
        "response_chars",
        "response_sha256",
        "checks",
        "error_code",
        "raw_response_retained",
    }
)
_CHECK_FIELDS = frozenset({"check_id", "passed", "weight"})
_CORPUS_FIELDS = frozenset(
    {"schema_version", "approval_workflow_version", "description", "batches"}
)
_BATCH_FIELDS = frozenset(
    {
        "approval_ref",
        "approval_status",
        "approval_signature",
        "approval_key_sha256",
        "evidence_sha256",
        "benchmark",
    }
)


def prepare_chat_model_benchmark_review(
    payload: Mapping[str, object],
    *,
    approval_ref: str,
) -> dict[str, object]:
    """Return the exact metadata-only artifact an operator must approve."""
    benchmark = validate_chat_model_benchmark_evidence_payload(payload)
    _require_safe_approval_ref(approval_ref)
    evidence_sha256 = _benchmark_digest(benchmark)
    return {
        "approval_workflow_version": CHAT_MODEL_BENCHMARK_APPROVAL_VERSION,
        "approval_ref": approval_ref,
        "approval_statement": chat_model_benchmark_approval_statement(
            approval_ref=approval_ref,
            evidence_sha256=evidence_sha256,
        ).decode("ascii"),
        "evidence_sha256": evidence_sha256,
        "benchmark": benchmark,
    }


def build_approved_chat_model_benchmark_evidence(
    payload: Mapping[str, object],
    *,
    approval_ref: str,
    approved_evidence_sha256: str,
    approval_signature: str,
    approval_public_key_pem: bytes,
    existing_corpus: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Append one independently approved benchmark to the evidence corpus."""
    review = prepare_chat_model_benchmark_review(payload, approval_ref=approval_ref)
    evidence_sha256 = str(review["evidence_sha256"])
    if approved_evidence_sha256 != evidence_sha256:
        raise ValueError("benchmark_evidence_approved_digest_mismatch")
    approval_key_sha256 = _verify_approval_signature(
        approval_ref=approval_ref,
        evidence_sha256=evidence_sha256,
        approval_signature=approval_signature,
        approval_public_key_pem=approval_public_key_pem,
    )
    corpus = (
        _empty_corpus()
        if existing_corpus is None
        else validate_chat_model_benchmark_evidence_corpus(
            existing_corpus,
            approval_public_key_pem=approval_public_key_pem,
        )
    )
    batches = list(_list_value(corpus.get("batches"), "benchmark_evidence_batches"))
    if len(batches) >= MAX_BENCHMARK_EVIDENCE_BATCHES:
        raise ValueError("benchmark_evidence_batch_limit_reached")
    if any(
        isinstance(batch, Mapping) and batch.get("approval_ref") == approval_ref
        for batch in batches
    ):
        raise ValueError("benchmark_evidence_approval_ref_duplicate")
    if any(
        isinstance(batch, Mapping) and batch.get("evidence_sha256") == evidence_sha256
        for batch in batches
    ):
        raise ValueError("benchmark_evidence_digest_duplicate")
    batches.append(
        {
            "approval_ref": approval_ref,
            "approval_status": "approved",
            "approval_signature": approval_signature,
            "approval_key_sha256": approval_key_sha256,
            "evidence_sha256": evidence_sha256,
            "benchmark": review["benchmark"],
        }
    )
    corpus["batches"] = batches
    return validate_chat_model_benchmark_evidence_corpus(
        corpus,
        approval_public_key_pem=approval_public_key_pem,
    )


def validate_chat_model_benchmark_evidence_payload(
    payload: Mapping[str, object],
) -> dict[str, object]:
    """Validate and canonicalize one live benchmark payload."""
    _require_only_fields(payload, _TOP_LEVEL_FIELDS, "benchmark_evidence_fields")
    if payload.get("schema_version") != CHAT_MODEL_TASK_BENCHMARK_SCHEMA_VERSION:
        raise ValueError("benchmark_evidence_schema_mismatch")
    if payload.get("benchmark_version") != CHAT_MODEL_TASK_BENCHMARK_VERSION:
        raise ValueError("benchmark_evidence_benchmark_version_mismatch")
    if payload.get("registry_version") != CHAT_MODEL_CAPABILITY_REGISTRY_VERSION:
        raise ValueError("benchmark_evidence_registry_version_mismatch")
    if payload.get("advisory_only") is not True:
        raise ValueError("benchmark_evidence_must_be_advisory")
    if payload.get("routing_scores_mutated") is not False:
        raise ValueError("benchmark_evidence_routing_mutation_not_allowed")
    _require_timestamp(payload.get("run_completed_at"))

    reporting = _mapping_value(payload.get("reporting"), "benchmark_evidence_reporting")
    _require_only_fields(
        reporting,
        frozenset({"model_calls", "raw_prompts_retained", "raw_responses_retained"}),
        "benchmark_evidence_reporting_fields",
    )
    model_calls = _bounded_int(reporting.get("model_calls"), 1, 64)
    if reporting.get("raw_prompts_retained") is not False:
        raise ValueError("benchmark_evidence_raw_prompt_retention_not_allowed")
    if reporting.get("raw_responses_retained") is not False:
        raise ValueError("benchmark_evidence_raw_response_retention_not_allowed")

    rows = _list_value(payload.get("results"), "benchmark_evidence_results")
    if len(rows) != model_calls:
        raise ValueError("benchmark_evidence_model_call_count_mismatch")
    results = tuple(_result_from_mapping(row) for row in rows)
    identities = {(result.route_mode, result.task_id) for result in results}
    if len(identities) != len(results):
        raise ValueError("benchmark_evidence_result_duplicate")

    expected = chat_model_task_benchmark_payload(results, model_calls=model_calls)
    if payload.get("scorecards") != expected["scorecards"]:
        raise ValueError("benchmark_evidence_scorecard_mismatch")
    for field in ("status", "passed", "failed"):
        if payload.get(field) != expected[field]:
            raise ValueError(f"benchmark_evidence_{field}_mismatch")

    # JSON round-trip removes custom mapping/list implementations before hashing.
    return json.loads(json.dumps(dict(payload), sort_keys=True))


def validate_chat_model_benchmark_evidence_corpus(
    corpus: Mapping[str, object],
    *,
    approval_public_key_pem: bytes,
) -> dict[str, object]:
    _require_only_fields(corpus, _CORPUS_FIELDS, "benchmark_evidence_corpus_fields")
    if corpus.get("schema_version") != CHAT_MODEL_BENCHMARK_EVIDENCE_SCHEMA_VERSION:
        raise ValueError("benchmark_evidence_corpus_schema_mismatch")
    if corpus.get("approval_workflow_version") != CHAT_MODEL_BENCHMARK_APPROVAL_VERSION:
        raise ValueError("benchmark_evidence_approval_version_mismatch")
    if corpus.get("description") != _empty_corpus()["description"]:
        raise ValueError("benchmark_evidence_description_mismatch")
    batches = _list_value(corpus.get("batches"), "benchmark_evidence_batches")
    if len(batches) > MAX_BENCHMARK_EVIDENCE_BATCHES:
        raise ValueError("benchmark_evidence_batch_limit_reached")
    approval_refs: set[str] = set()
    evidence_digests: set[str] = set()
    validated_batches: list[dict[str, object]] = []
    for item in batches:
        batch = _mapping_value(item, "benchmark_evidence_batch")
        _require_only_fields(batch, _BATCH_FIELDS, "benchmark_evidence_batch_fields")
        approval_ref = str(batch.get("approval_ref") or "")
        _require_safe_approval_ref(approval_ref)
        if approval_ref in approval_refs:
            raise ValueError("benchmark_evidence_approval_ref_duplicate")
        approval_refs.add(approval_ref)
        if batch.get("approval_status") != "approved":
            raise ValueError("benchmark_evidence_approval_required")
        benchmark = validate_chat_model_benchmark_evidence_payload(
            _mapping_value(batch.get("benchmark"), "benchmark_evidence_benchmark")
        )
        evidence_sha256 = str(batch.get("evidence_sha256") or "")
        if evidence_sha256 != _benchmark_digest(benchmark):
            raise ValueError("benchmark_evidence_digest_mismatch")
        if evidence_sha256 in evidence_digests:
            raise ValueError("benchmark_evidence_digest_duplicate")
        evidence_digests.add(evidence_sha256)
        key_sha256 = _verify_approval_signature(
            approval_ref=approval_ref,
            evidence_sha256=evidence_sha256,
            approval_signature=str(batch.get("approval_signature") or ""),
            approval_public_key_pem=approval_public_key_pem,
            expected_key_sha256=str(batch.get("approval_key_sha256") or ""),
        )
        validated_batches.append(
            {
                **dict(batch),
                "approval_key_sha256": key_sha256,
                "benchmark": benchmark,
            }
        )
    return {**dict(corpus), "batches": validated_batches}


def chat_model_benchmark_comparison(
    corpus: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return latest approved task evidence per registered model."""
    batches = [] if corpus is None else list(corpus.get("batches") or [])
    latest: dict[str, dict[str, object]] = {}
    for item in batches:
        batch = _mapping_value(item, "benchmark_evidence_batch")
        benchmark = _mapping_value(
            batch.get("benchmark"), "benchmark_evidence_benchmark"
        )
        for scorecard_item in _list_value(
            benchmark.get("scorecards"), "benchmark_evidence_scorecards"
        ):
            scorecard = _mapping_value(scorecard_item, "benchmark_evidence_scorecard")
            route_mode = str(scorecard.get("route_mode") or "")
            latest[route_mode] = {
                **dict(scorecard),
                "approval_ref": batch.get("approval_ref"),
                "evidence_sha256": batch.get("evidence_sha256"),
                "run_completed_at": benchmark.get("run_completed_at"),
            }
    models = [
        latest[capability.route_mode]
        for capability in DEFAULT_CHAT_MODEL_CAPABILITIES
        if capability.route_mode in latest
    ]
    return {
        "schema_version": CHAT_MODEL_BENCHMARK_COMPARISON_VERSION,
        "status": "ready" if models else "empty",
        "benchmark_version": CHAT_MODEL_TASK_BENCHMARK_VERSION,
        "registry_version": CHAT_MODEL_CAPABILITY_REGISTRY_VERSION,
        "approved_batch_count": len(batches),
        "approved_model_count": len(models),
        "models": models,
        "advisory_only": True,
        "routing_scores_mutated": False,
        "routing_eligible": False,
    }


def load_chat_model_benchmark_evidence(
    path: Path,
    *,
    approval_public_key_pem: bytes,
) -> dict[str, object]:
    try:
        payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("benchmark_evidence_store_unreadable") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("benchmark_evidence_corpus_object_required")
    return validate_chat_model_benchmark_evidence_corpus(
        payload,
        approval_public_key_pem=approval_public_key_pem,
    )


def load_chat_model_benchmark_approval_public_key(path: Path) -> bytes:
    try:
        expanded = path.expanduser()
        if expanded.stat().st_size > MAX_APPROVAL_PUBLIC_KEY_BYTES:
            raise ValueError("benchmark_evidence_approval_public_key_too_large")
        value = expanded.read_bytes()
    except OSError as exc:
        raise ValueError("benchmark_evidence_approval_public_key_unreadable") from exc
    if not value:
        raise ValueError("benchmark_evidence_approval_public_key_invalid")
    return value


def chat_model_benchmark_approval_statement(
    *,
    approval_ref: str,
    evidence_sha256: str,
) -> bytes:
    _require_safe_approval_ref(approval_ref)
    if not _SHA256_RE.fullmatch(evidence_sha256):
        raise ValueError("benchmark_evidence_approved_digest_invalid")
    return (
        f"{CHAT_MODEL_BENCHMARK_APPROVAL_VERSION}\n{approval_ref}\n{evidence_sha256}\n"
    ).encode("ascii")


def _result_from_mapping(item: object) -> ChatModelTaskBenchmarkResult:
    row = _mapping_value(item, "benchmark_evidence_result")
    _require_only_fields(row, _RESULT_FIELDS, "benchmark_evidence_result_fields")
    if row.get("schema_version") != CHAT_MODEL_TASK_BENCHMARK_SCHEMA_VERSION:
        raise ValueError("benchmark_evidence_result_schema_mismatch")
    if row.get("benchmark_version") != CHAT_MODEL_TASK_BENCHMARK_VERSION:
        raise ValueError("benchmark_evidence_result_benchmark_mismatch")
    if row.get("registry_version") != CHAT_MODEL_CAPABILITY_REGISTRY_VERSION:
        raise ValueError("benchmark_evidence_result_registry_mismatch")
    route_mode = _safe_token(row.get("route_mode"), "route_mode")
    capability = get_chat_model_capability(route_mode)
    if capability is None:
        raise ValueError("benchmark_evidence_unknown_route")
    task_id = _safe_token(row.get("task_id"), "task_id")
    task = next(
        (
            item
            for item in DEFAULT_CHAT_MODEL_BENCHMARK_TASKS
            if item.task_id == task_id
        ),
        None,
    )
    if task is None or row.get("task_class") != task.task_class:
        raise ValueError("benchmark_evidence_task_mismatch")
    expected_identity = {
        "provider": capability.provider,
        "model_id": capability.model_id,
        "deployment": capability.deployment,
        "privacy_tier": capability.privacy_tier,
        "cost_tier": capability.cost_tier,
        "registry_task_score": capability.task_scores[task.task_class],
        "minimum_score": task.minimum_score,
    }
    if any(row.get(field) != value for field, value in expected_identity.items()):
        raise ValueError("benchmark_evidence_model_identity_mismatch")
    checks = tuple(
        _validated_check(check, task)
        for check in _list_value(row.get("checks"), "benchmark_evidence_checks")
    )
    if len(checks) != len(task.checks):
        raise ValueError("benchmark_evidence_check_count_mismatch")
    if {str(check["check_id"]) for check in checks} != {
        check.check_id for check in task.checks
    }:
        raise ValueError("benchmark_evidence_check_mismatch")
    score = _bounded_int(row.get("score"), 0, 100)
    expected_score = sum(
        int(check["weight"]) for check in checks if check["passed"] is True
    )
    if score != expected_score:
        raise ValueError("benchmark_evidence_score_mismatch")
    passed = row.get("passed")
    if not isinstance(passed, bool):
        raise ValueError("benchmark_evidence_passed_invalid")
    error_code = row.get("error_code")
    if error_code is not None and error_code not in {
        "model_call_failed",
        "model_adapter_exception",
        "model_identity_mismatch",
        "route_mismatch",
    }:
        raise ValueError("benchmark_evidence_error_code_invalid")
    if passed != (error_code is None and score >= task.minimum_score):
        raise ValueError("benchmark_evidence_passed_mismatch")
    if row.get("raw_response_retained") is not False:
        raise ValueError("benchmark_evidence_raw_response_retention_not_allowed")
    response_sha256 = str(row.get("response_sha256") or "")
    if not _RAW_SHA256_RE.fullmatch(response_sha256):
        raise ValueError("benchmark_evidence_response_digest_invalid")
    return ChatModelTaskBenchmarkResult(
        task_id=task_id,
        task_class=task.task_class,
        route_mode=route_mode,
        provider=capability.provider,
        model_id=capability.model_id,
        deployment=capability.deployment,
        privacy_tier=capability.privacy_tier,
        cost_tier=capability.cost_tier,
        registry_task_score=capability.task_scores[task.task_class],
        score=score,
        minimum_score=task.minimum_score,
        passed=passed,
        latency_ms=_bounded_int(row.get("latency_ms"), 0, 3_600_000),
        response_chars=_bounded_int(row.get("response_chars"), 0, 1_000_000),
        response_sha256=response_sha256,
        checks=checks,
        error_code=error_code if isinstance(error_code, str) else None,
    )


def _validated_check(
    item: object,
    task: ChatModelBenchmarkTask,
) -> dict[str, object]:
    check = _mapping_value(item, "benchmark_evidence_check")
    _require_only_fields(check, _CHECK_FIELDS, "benchmark_evidence_check_fields")
    expected_checks = {candidate.check_id: candidate for candidate in task.checks}
    check_id = _safe_token(check.get("check_id"), "check_id")
    expected = expected_checks.get(check_id)
    if expected is None or check.get("weight") != expected.weight:
        raise ValueError("benchmark_evidence_check_mismatch")
    if not isinstance(check.get("passed"), bool):
        raise ValueError("benchmark_evidence_check_passed_invalid")
    return dict(check)


def _verify_approval_signature(
    *,
    approval_ref: str,
    evidence_sha256: str,
    approval_signature: str,
    approval_public_key_pem: bytes,
    expected_key_sha256: str | None = None,
) -> str:
    if len(approval_public_key_pem) > MAX_APPROVAL_PUBLIC_KEY_BYTES:
        raise ValueError("benchmark_evidence_approval_public_key_too_large")
    if not 1 <= len(approval_signature) <= 256:
        raise ValueError("benchmark_evidence_approval_signature_invalid")
    try:
        public_key = serialization.load_pem_public_key(approval_public_key_pem)
    except (TypeError, ValueError) as exc:
        raise ValueError("benchmark_evidence_approval_public_key_invalid") from exc
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValueError("benchmark_evidence_approval_public_key_invalid")
    key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key_sha256 = stable_hash(key_bytes, namespace="chat_model_benchmark_approval_key")
    if expected_key_sha256 is not None and expected_key_sha256 != key_sha256:
        raise ValueError("benchmark_evidence_approval_key_mismatch")
    try:
        signature = base64.b64decode(approval_signature, validate=True)
        public_key.verify(
            signature,
            chat_model_benchmark_approval_statement(
                approval_ref=approval_ref,
                evidence_sha256=evidence_sha256,
            ),
        )
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("benchmark_evidence_approval_signature_invalid") from exc
    return key_sha256


def _benchmark_digest(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return stable_hash(canonical, namespace="chat_model_benchmark_evidence")


def _empty_corpus() -> dict[str, object]:
    return {
        "schema_version": CHAT_MODEL_BENCHMARK_EVIDENCE_SCHEMA_VERSION,
        "approval_workflow_version": CHAT_MODEL_BENCHMARK_APPROVAL_VERSION,
        "description": (
            "Operator-approved metadata-only model benchmark evidence. Raw prompts "
            "and responses are prohibited, and evidence is never routing-eligible."
        ),
        "batches": [],
    }


def _require_only_fields(
    value: Mapping[str, object],
    allowed: frozenset[str],
    error: str,
) -> None:
    if set(value) != allowed:
        raise ValueError(error)


def _mapping_value(value: object, error: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(error)
    return dict(value)


def _list_value(value: object, error: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(error)
    return value


def _safe_token(value: object, field: str) -> str:
    token = str(value or "")
    if not _SAFE_TOKEN_RE.fullmatch(token):
        raise ValueError(f"benchmark_evidence_{field}_invalid")
    return token


def _require_safe_approval_ref(value: str) -> None:
    if not _SAFE_APPROVAL_REF_RE.fullmatch(value):
        raise ValueError("benchmark_evidence_approval_ref_invalid")


def _bounded_int(value: object, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("benchmark_evidence_integer_invalid")
    if not minimum <= value <= maximum:
        raise ValueError("benchmark_evidence_integer_out_of_range")
    return value


def _require_timestamp(value: object) -> None:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("benchmark_evidence_run_completed_at_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("benchmark_evidence_run_completed_at_invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("benchmark_evidence_run_completed_at_invalid")
