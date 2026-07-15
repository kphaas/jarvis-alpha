from __future__ import annotations

import base64
from copy import deepcopy
import json
import subprocess
import sys
from dataclasses import asdict

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from brain.services import chat_evaluation_harness
from brain.services.chat_redacted_trace_corpus import (
    ASSISTED_PROBE_EVIDENCE_LANE,
    CHAT_TRACE_APPROVAL_PUBLIC_KEY_PATH_ENV,
    CHAT_TRACE_SAMPLE_RETENTION_POLICY,
    CHAT_TRACE_REDACTION_POLICY_VERSION,
    CHAT_TRACE_SAMPLING_WORKFLOW_VERSION,
    HISTORICAL_RAW_EVIDENCE_LANE,
    HISTORICAL_RAW_SELECTION_METHOD,
    HISTORICAL_RAW_SOURCE_SYSTEM,
    LEGACY_UNCLASSIFIED_EVIDENCE_LANE,
    REDACTED_TRACE_CORPUS_PATH,
    build_approved_trace_sample_corpus as _build_approved_trace_sample_corpus,
    load_redacted_trace_corpus,
    prepare_trace_sample_review_artifact,
    redact_chat_trace_candidate,
    trace_sample_approval_statement,
    validate_redacted_trace_case,
)
from brain.privacy.redaction import stable_hash


_TEST_APPROVAL_PRIVATE_KEY = Ed25519PrivateKey.generate()
_TEST_APPROVAL_PUBLIC_KEY = _TEST_APPROVAL_PRIVATE_KEY.public_key()
_TEST_APPROVAL_PUBLIC_KEY_PEM = _TEST_APPROVAL_PUBLIC_KEY.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)
_TEST_APPROVAL_KEY_SHA256 = stable_hash(
    _TEST_APPROVAL_PUBLIC_KEY.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ),
    namespace="chat_trace_approval_key",
)


def test_redacts_chat_trace_candidate_without_raw_sensitive_text() -> None:
    redacted = redact_chat_trace_candidate(
        {
            "name": "raw_candidate",
            "trace_id": "11111111-2222-3333-4444-555555555555",
            "prompt": "Ken Haas asked from ken@example.com about docs.",
            "requested_model": "auto",
            "internet_mode": "web_search",
            "memory_context": "Ken Haas remembered beta.openai.com.",
            "internet_context": "Official source: platform.openai.com/docs",
            "response_text": "Call 404-555-1212. Use platform.openai.com/docs.",
            "expected_route_mode": "perplexity",
            "expected_quality_action": "accept",
            "expected_escalation": "none",
            "expected_tool_policy": "beacon_evidence_is_authority",
            "raw_transcript": "must not survive",
            "private_note": "must also not survive",
        },
        sensitive_terms=("Ken Haas",),
    )
    rendered = json.dumps(redacted)

    assert redacted["redaction"]["policy_version"] == (
        CHAT_TRACE_REDACTION_POLICY_VERSION
    )
    assert redacted["redaction"]["raw_trace_text_retained"] is False
    assert redacted["redaction"]["source_trace_hash"].startswith("sha256:")
    assert "raw_transcript" not in redacted
    assert "private_note" not in redacted
    assert redacted["trace_id"].startswith("redacted-trace-")
    assert "11111111-2222-3333-4444-555555555555" not in rendered
    assert "Ken Haas" not in rendered
    assert "ken@example.com" not in rendered
    assert "404-555-1212" not in rendered
    assert "[term:" in rendered
    assert "[email:" in rendered
    assert "[phone:" in rendered


def test_committed_redacted_trace_corpus_loads_without_raw_contact_leaks() -> None:
    cases = load_redacted_trace_corpus()
    rendered = json.dumps([asdict(case) for case in cases])

    assert len(cases) == 3
    assert cases[0].redaction_policy_version == CHAT_TRACE_REDACTION_POLICY_VERSION
    assert cases[0].source_trace_hash.startswith("sha256:")
    contract_failure = next(
        case for case in cases if case.trace_kind == "output_contract_failure"
    )
    assert contract_failure.expected_route_mode == "local"
    assert contract_failure.expected_quality_action == "replace_with_safe_fallback"
    assert contract_failure.expected_escalation == "operator_review"
    assert contract_failure.expected_repair_action == "retry_local_once"
    assert contract_failure.expected_repaired is False
    assert contract_failure.expected_output_contract_passed is False
    assert contract_failure.expected_output_contract_issues == (
        "forbidden_content_present",
        "required_order_invalid",
    )
    assert contract_failure.expected_output_contract_feasible is None
    assert contract_failure.evidence_lane == LEGACY_UNCLASSIFIED_EVIDENCE_LANE
    feasible_failure = next(
        case for case in cases if case.expected_output_contract_feasible is True
    )
    assert feasible_failure.expected_output_contract_issues == (
        "required_order_invalid",
    )
    assert feasible_failure.evidence_lane == ASSISTED_PROBE_EVIDENCE_LANE
    assert "ken@example.com" not in rendered
    assert "404-555-1212" not in rendered
    assert "Ken Haas" not in rendered


def test_builds_approved_trace_sample_manifest_and_replay_case(tmp_path) -> None:
    corpus = build_approved_trace_sample_corpus(
        _sample_payload(),
        approval_ref="phase25-approved-001",
    )
    rendered = json.dumps(corpus)
    output = tmp_path / "corpus.json"
    output.write_text(json.dumps(corpus), encoding="utf-8")
    cases = load_redacted_trace_corpus(
        output,
        approval_public_key_pem=_TEST_APPROVAL_PUBLIC_KEY_PEM,
    )

    assert corpus["sampling_workflow_version"] == (CHAT_TRACE_SAMPLING_WORKFLOW_VERSION)
    assert corpus["sampling_batches"] == [
        {
            "workflow_version": CHAT_TRACE_SAMPLING_WORKFLOW_VERSION,
            "approval_ref": "phase25-approved-001",
            "approved_redacted_content_sha256": (
                prepare_trace_sample_review_artifact(_sample_payload())[
                    "redacted_content_sha256"
                ]
            ),
            "approval_key_sha256": _TEST_APPROVAL_KEY_SHA256,
            "approval_signature": _approval_signature(
                "phase25-approved-001",
                str(
                    prepare_trace_sample_review_artifact(_sample_payload())[
                        "redacted_content_sha256"
                    ]
                ),
            ),
            "approval_status": "approved",
            "purpose": "offline_quality_eval",
            "sensitive_terms_reviewed": True,
            "raw_source_retention": CHAT_TRACE_SAMPLE_RETENTION_POLICY,
            "raw_trace_text_retained": False,
            "sampled_case_count": 1,
            "source_trace_hashes": [
                corpus["cases"][0]["redaction"]["source_trace_hash"]
            ],
        }
    ]
    assert cases[0].expected_route_mode == "local"
    assert cases[0].expected_quality_action == "accept"
    assert cases[0].expected_tool_policy == "no_external_tool_executed"
    assert cases[0].name.startswith("sampled_real_trace_")
    assert "local_accept" not in cases[0].name
    assert cases[0].trace_id.startswith("redacted-trace-")
    assert "Ken Haas" not in rendered
    assert "real-message-id-123" not in rendered
    assert "private_note" not in rendered


def test_sampled_trace_replays_through_quality_pipeline(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = build_approved_trace_sample_corpus(
        _sample_payload(),
        approval_ref="phase25-approved-001",
    )
    output = tmp_path / "corpus.json"
    output.write_text(json.dumps(corpus), encoding="utf-8")
    sampled_cases = load_redacted_trace_corpus(
        output,
        approval_public_key_pem=_TEST_APPROVAL_PUBLIC_KEY_PEM,
    )
    monkeypatch.setattr(
        chat_evaluation_harness,
        "load_redacted_trace_corpus",
        lambda: sampled_cases,
    )

    results = [
        result
        for result in chat_evaluation_harness.run_chat_eval_harness()
        if result.eval_group == "redacted_trace_corpus"
    ]

    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].details["raw_trace_text_retained"] is False


def test_signed_contract_failure_replays_post_repair_quality_gate(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = build_approved_trace_sample_corpus(
        _contract_failure_payload(),
        approval_ref="phase31-contract-failure-001",
    )
    output = tmp_path / "contract-failure-corpus.json"
    output.write_text(json.dumps(corpus), encoding="utf-8")
    sampled_cases = load_redacted_trace_corpus(
        output,
        approval_public_key_pem=_TEST_APPROVAL_PUBLIC_KEY_PEM,
    )
    monkeypatch.setattr(
        chat_evaluation_harness,
        "load_redacted_trace_corpus",
        lambda: sampled_cases,
    )

    results = [
        result
        for result in chat_evaluation_harness.run_chat_eval_harness()
        if result.eval_group == "redacted_trace_corpus"
    ]

    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].details["trace_kind"] == "output_contract_failure"
    assert results[0].details["replay_stage"] == "post_repair"
    assert results[0].details["output_contract_id"] == "exact_json"
    assert results[0].details["output_contract_passed"] is False
    assert results[0].details["output_contract_issues"] == ["json_object_required"]
    assert results[0].details["output_contract_feasible"] is True
    assert results[0].details["evidence_lane"] == ASSISTED_PROBE_EVIDENCE_LANE
    assert results[0].details["quality_action"] == "replace_with_safe_fallback"
    assert results[0].details["escalation_rung"] == "operator_review"
    assert results[0].details["repair_action"] == "retry_local_once"
    assert results[0].details["repair_replayed"] is False
    assert "Ken Haas" not in json.dumps(results[0].details)


def test_signed_historical_failure_replays_attested_provenance(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = build_approved_trace_sample_corpus(
        _historical_contract_failure_payload(),
        approval_ref="phase36-historical-failure-001",
    )
    output = tmp_path / "historical-failure-corpus.json"
    output.write_text(json.dumps(corpus), encoding="utf-8")
    sampled_cases = load_redacted_trace_corpus(
        output,
        approval_public_key_pem=_TEST_APPROVAL_PUBLIC_KEY_PEM,
    )
    monkeypatch.setattr(
        chat_evaluation_harness,
        "load_redacted_trace_corpus",
        lambda: sampled_cases,
    )

    result = next(
        result
        for result in chat_evaluation_harness.run_chat_eval_harness()
        if result.eval_group == "redacted_trace_corpus"
    )

    assert result.passed is True
    assert result.details["evidence_lane"] == HISTORICAL_RAW_EVIDENCE_LANE
    assert result.details["historical_source_system"] == (HISTORICAL_RAW_SOURCE_SYSTEM)
    assert result.details["historical_selection_method"] == (
        HISTORICAL_RAW_SELECTION_METHOD
    )
    assert result.details["historical_operator_attested"] is True


def test_contract_failure_sampling_requires_failed_post_repair_outcome() -> None:
    payload = _contract_failure_payload()
    payload["candidates"][0]["outcome"]["chat_output_contract_passed"] = True

    with pytest.raises(
        ValueError,
        match="trace_sampling_output_contract_failure_required",
    ):
        prepare_trace_sample_review_artifact(payload)


def test_contract_failure_sampling_requires_reproducible_contract_issues() -> None:
    payload = _contract_failure_payload()
    payload["candidates"][0]["outcome"]["chat_output_contract_issues"] = [
        "json_keys_mismatch"
    ]

    with pytest.raises(
        ValueError,
        match="redacted_trace_output_contract_issues_mismatch",
    ):
        prepare_trace_sample_review_artifact(payload)


def test_trace_hash_digits_do_not_trigger_contact_leak_false_positive() -> None:
    payload = _contract_failure_payload()
    payload["candidates"][0]["source_trace_id"] = "phase35-assisted-probe-07"

    review = prepare_trace_sample_review_artifact(payload)

    assert review["sampled_case_count"] == 1


def test_contract_failure_sampling_requires_phase33_feasibility_metadata() -> None:
    payload = _contract_failure_payload()
    outcome = payload["candidates"][0]["outcome"]
    outcome["chat_output_contract_feasible"] = False
    outcome["chat_output_contract_conflict_count"] = 1
    outcome["chat_output_contract_conflicts"] = ["required_term_forbidden"]
    outcome["chat_output_contract_preflight_action"] = "skip_generation"

    with pytest.raises(
        ValueError,
        match="trace_sampling_output_contract_feasibility_required",
    ):
        prepare_trace_sample_review_artifact(payload)


def test_contract_failure_sampling_requires_explicit_evidence_lane() -> None:
    payload = _contract_failure_payload()
    del payload["candidates"][0]["evidence_lane"]

    with pytest.raises(
        ValueError,
        match="trace_sampling_contract_failure_evidence_lane_required",
    ):
        prepare_trace_sample_review_artifact(payload)


@pytest.mark.parametrize(
    "field",
    [
        "historical_source_system",
        "historical_selection_method",
        "historical_operator_attested",
    ],
)
def test_historical_failure_sampling_requires_complete_provenance(field: str) -> None:
    payload = _historical_contract_failure_payload()
    del payload["candidates"][0][field]

    with pytest.raises(
        ValueError,
        match="trace_sampling_historical_provenance_required",
    ):
        prepare_trace_sample_review_artifact(payload)


def test_historical_failure_sampling_rejects_invalid_provenance() -> None:
    payload = _historical_contract_failure_payload()
    payload["candidates"][0]["historical_operator_attested"] = False

    with pytest.raises(
        ValueError,
        match="trace_sampling_historical_provenance_invalid",
    ):
        prepare_trace_sample_review_artifact(payload)


def test_assisted_probe_rejects_historical_provenance() -> None:
    payload = _contract_failure_payload()
    payload["candidates"][0].update(
        {
            "historical_source_system": HISTORICAL_RAW_SOURCE_SYSTEM,
            "historical_selection_method": HISTORICAL_RAW_SELECTION_METHOD,
            "historical_operator_attested": True,
        }
    )

    with pytest.raises(
        ValueError,
        match="trace_sampling_historical_provenance_not_allowed",
    ):
        prepare_trace_sample_review_artifact(payload)


def test_contract_failure_sampling_rejects_mixed_evidence_lanes() -> None:
    payload = _historical_contract_failure_payload()
    assisted_candidate = deepcopy(_contract_failure_payload()["candidates"][0])
    assisted_candidate["source_trace_id"] = "phase36-assisted-mixed-source-001"
    payload["candidates"].append(assisted_candidate)

    with pytest.raises(
        ValueError,
        match="trace_sampling_contract_failure_evidence_lanes_mixed",
    ):
        prepare_trace_sample_review_artifact(payload)


def test_phase35_metadata_rejects_legacy_infeasible_contract_failure() -> None:
    corpus = json.loads(REDACTED_TRACE_CORPUS_PATH.read_text(encoding="utf-8"))
    case = next(
        item
        for item in corpus["cases"]
        if item.get("trace_kind") == "output_contract_failure"
    )
    case["expected_output_contract_feasible"] = True
    case["evidence_lane"] = ASSISTED_PROBE_EVIDENCE_LANE

    with pytest.raises(
        ValueError,
        match="redacted_trace_output_contract_not_feasible",
    ):
        validate_redacted_trace_case(case)


def test_general_sampling_rejects_output_contract_metadata() -> None:
    payload = _contract_failure_payload()
    payload["candidates"][0]["trace_kind"] = "general"

    with pytest.raises(
        ValueError,
        match="trace_sampling_output_contract_metadata_not_allowed",
    ):
        prepare_trace_sample_review_artifact(payload)


def test_signed_trace_corpus_loads_with_configured_public_key(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = build_approved_trace_sample_corpus(
        _sample_payload(),
        approval_ref="phase25-approved-001",
    )
    output = tmp_path / "signed-corpus.json"
    key_path = tmp_path / "approval-public-key.pem"
    output.write_text(json.dumps(corpus), encoding="utf-8")
    key_path.write_bytes(_TEST_APPROVAL_PUBLIC_KEY_PEM)

    monkeypatch.delenv(CHAT_TRACE_APPROVAL_PUBLIC_KEY_PATH_ENV, raising=False)
    with pytest.raises(ValueError, match="redacted_trace_approval_public_key_required"):
        load_redacted_trace_corpus(output)

    monkeypatch.setenv(CHAT_TRACE_APPROVAL_PUBLIC_KEY_PATH_ENV, str(key_path))

    cases = load_redacted_trace_corpus(output)

    assert len(cases) == 1


@pytest.mark.parametrize(
    ("approval_patch", "expected_error"),
    [
        ({"status": "pending"}, "trace_sampling_approval_required"),
        (
            {"sensitive_terms_reviewed": False},
            "trace_sampling_sensitive_terms_review_required",
        ),
        (
            {"raw_source_retention": "keep"},
            "trace_sampling_retention_policy_required",
        ),
    ],
)
def test_trace_sampling_fails_closed_without_approval_and_retention(
    approval_patch: dict[str, object],
    expected_error: str,
) -> None:
    payload = _sample_payload()
    payload["approval"].update(approval_patch)

    with pytest.raises(ValueError, match=expected_error):
        build_approved_trace_sample_corpus(
            payload,
            approval_ref="phase25-approved-001",
        )


def test_trace_sampling_binds_approval_to_reviewed_redacted_content() -> None:
    payload = _sample_payload()
    review = prepare_trace_sample_review_artifact(payload)
    approved_digest = str(review["redacted_content_sha256"])
    approval_signature = _approval_signature(
        "phase25-approved-001",
        approved_digest,
    )
    payload["candidates"][0]["prompt"] = "Substituted private medical detail."

    with pytest.raises(ValueError, match="trace_sampling_approved_digest_mismatch"):
        _build_approved_trace_sample_corpus(
            payload,
            approval_ref="phase25-approved-001",
            approved_redacted_content_sha256=approved_digest,
            approval_signature=approval_signature,
            approval_public_key_pem=_TEST_APPROVAL_PUBLIC_KEY_PEM,
        )


def test_trace_sampling_rejects_post_approval_corpus_edits(tmp_path) -> None:
    corpus = build_approved_trace_sample_corpus(
        _sample_payload(),
        approval_ref="phase25-approved-001",
    )
    corpus["cases"][0]["prompt"] = "Changed after approval."
    output = tmp_path / "changed-corpus.json"
    output.write_text(json.dumps(corpus), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="redacted_trace_sampling_batch_digest_mismatch",
    ):
        load_redacted_trace_corpus(
            output,
            approval_public_key_pem=_TEST_APPROVAL_PUBLIC_KEY_PEM,
        )


def test_trace_sampling_rejects_forged_post_approval_digest(tmp_path) -> None:
    corpus = build_approved_trace_sample_corpus(
        _sample_payload(),
        approval_ref="phase25-approved-001",
    )
    corpus["cases"][0]["prompt"] = "Changed after signed approval."
    changed_cases = corpus["cases"]
    changed_digest = stable_hash(
        json.dumps(
            changed_cases,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ),
        namespace="chat_trace_review_content",
    )
    corpus["sampling_batches"][0]["approved_redacted_content_sha256"] = changed_digest
    output = tmp_path / "forged-corpus.json"
    output.write_text(json.dumps(corpus), encoding="utf-8")

    with pytest.raises(ValueError, match="trace_sampling_approval_signature_invalid"):
        load_redacted_trace_corpus(
            output,
            approval_public_key_pem=_TEST_APPROVAL_PUBLIC_KEY_PEM,
        )


def test_trace_sampling_rejects_unsigned_case_beside_signed_batch(tmp_path) -> None:
    corpus = build_approved_trace_sample_corpus(
        _sample_payload(),
        approval_ref="phase25-approved-001",
    )
    unsigned_case = redact_chat_trace_candidate(
        {
            "name": "unsigned_extra_case",
            "source_trace_id": "unsigned-source-id",
            "prompt": "Unsigned Person requested a private summary.",
            "requested_model": "auto",
            "internet_mode": "none",
            "memory_context": "",
            "internet_context": None,
            "response_text": "A summary was returned.",
            "expected_route_mode": "local",
            "expected_quality_action": "accept",
            "expected_escalation": "none",
            "expected_tool_policy": "no_external_tool_executed",
        },
        sensitive_terms=("Unsigned Person",),
    )
    corpus["cases"].append(unsigned_case)
    output = tmp_path / "unsigned-extra-case.json"
    output.write_text(json.dumps(corpus), encoding="utf-8")

    with pytest.raises(ValueError, match="redacted_trace_sampling_case_unsigned"):
        load_redacted_trace_corpus(
            output,
            approval_public_key_pem=_TEST_APPROVAL_PUBLIC_KEY_PEM,
        )


@pytest.mark.parametrize("sensitive_terms", [[], ["term-not-present-in-trace"]])
def test_trace_sampling_requires_effective_operator_redaction(
    sensitive_terms: list[str],
) -> None:
    payload = _sample_payload()
    payload["candidates"][0]["sensitive_terms"] = sensitive_terms

    expected = (
        "trace_sampling_sensitive_terms_required"
        if not sensitive_terms
        else "trace_sampling_redaction_required"
    )
    with pytest.raises(ValueError, match=expected):
        prepare_trace_sample_review_artifact(payload)


def test_trace_sampling_rejects_unknown_fields_duplicates_and_secret_leaks() -> None:
    unknown = _sample_payload()
    unknown["candidates"][0]["private_note"] = "must not be accepted"
    with pytest.raises(ValueError, match="trace_sampling_candidate_fields_not_allowed"):
        build_approved_trace_sample_corpus(
            unknown,
            approval_ref="phase25-approved-001",
        )

    payload = _sample_payload()
    corpus = build_approved_trace_sample_corpus(
        payload,
        approval_ref="phase25-approved-001",
    )
    poisoned_corpus = json.loads(json.dumps(corpus))
    poisoned_corpus["cases"][0]["redaction"]["private_note"] = "must not survive"
    payload["approval"]["approval_ref"] = "phase25-approved-002"
    with pytest.raises(
        ValueError,
        match="redacted_trace_redaction_fields_not_allowed",
    ):
        build_approved_trace_sample_corpus(
            payload,
            approval_ref="phase25-approved-002",
            existing_corpus=poisoned_corpus,
        )

    payload["approval"]["approval_ref"] = "phase25-approved-002"
    with pytest.raises(ValueError, match="trace_sampling_source_duplicate"):
        build_approved_trace_sample_corpus(
            payload,
            approval_ref="phase25-approved-002",
            existing_corpus=corpus,
        )

    secret = _sample_payload()
    secret["candidates"][0]["prompt"] = "Use api_key=not-a-real-secret-value"
    with pytest.raises(ValueError, match="redacted_trace_secret_leak"):
        build_approved_trace_sample_corpus(
            secret,
            approval_ref="phase25-approved-001",
        )


@pytest.mark.parametrize(
    "provider_secret",
    [
        "AKIAIOSFODNN7EXAMPLE",
        "sk-proj-1234567890abcdefghijkl",
        "sk-ant-api03-1234567890abcdefghijkl",
        "AIzaSyA1234567890abcdefghijkl",
        "ghp_1234567890abcdefghijkl",
        "eyJabcdefghijk.abcdefghijk.abcdefghijk",
    ],
)
def test_trace_sampling_rejects_provider_native_credentials(
    provider_secret: str,
) -> None:
    payload = _sample_payload()
    payload["candidates"][0]["prompt"] = (
        f"Ken Haas supplied native credential {provider_secret}."
    )

    with pytest.raises(ValueError, match="redacted_trace_secret_leak"):
        prepare_trace_sample_review_artifact(payload)


def test_trace_sampling_script_exports_only_redacted_corpus(tmp_path) -> None:
    source = tmp_path / "approved-source.json"
    review_output = tmp_path / "redacted-review.json"
    output = tmp_path / "redacted-corpus.json"
    public_key = tmp_path / "approval-public-key.pem"
    source.write_text(json.dumps(_sample_payload()), encoding="utf-8")
    public_key.write_bytes(_TEST_APPROVAL_PUBLIC_KEY_PEM)

    prepared = subprocess.run(
        [
            sys.executable,
            "scripts/sample_chat_traces.py",
            "--input",
            str(source),
            "--prepare-review-output",
            str(review_output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    review_summary = json.loads(prepared.stdout)
    assert review_summary["status"] == "prepared_for_review"
    assert review_summary["contract_failure_case_count"] == 0
    assert review_summary["feasible_contract_failure_case_count"] == 0
    assert review_summary["assisted_probe_case_count"] == 0
    assert review_summary["historical_raw_case_count"] == 0
    assert review_summary["review_artifact_cleanup_required"] is True
    assert "Ken Haas" not in review_output.read_text(encoding="utf-8")

    export_args = [
        sys.executable,
        "scripts/sample_chat_traces.py",
        "--input",
        str(source),
        "--output",
        str(output),
        "--approval-ref",
        "phase25-approved-001",
        "--approved-redacted-content-sha256",
        review_summary["redacted_content_sha256"],
        "--approval-signature",
        _approval_signature(
            "phase25-approved-001",
            review_summary["redacted_content_sha256"],
        ),
        "--approval-public-key",
        str(public_key),
        "--review-artifact",
        str(review_output),
    ]
    rejected = subprocess.run(
        export_args,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode == 2
    assert "trace_sampling_delete_confirmation_required" in rejected.stderr
    assert source.exists()
    assert review_output.exists()
    assert not output.exists()

    completed = subprocess.run(
        [*export_args, "--delete-inputs-after-export"],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    rendered = output.read_text(encoding="utf-8")
    assert summary["status"] == "exported"
    assert summary["sampled_case_count"] == 1
    assert summary["contract_failure_case_count"] == 0
    assert summary["feasible_contract_failure_case_count"] == 0
    assert summary["assisted_probe_case_count"] == 0
    assert summary["historical_raw_case_count"] == 0
    assert summary["raw_trace_text_retained"] is False
    assert summary["raw_source_deleted"] is True
    assert summary["review_artifact_deleted"] is True
    assert not source.exists()
    assert not review_output.exists()
    assert "Ken Haas" not in completed.stdout
    assert "Ken Haas" not in rendered
    assert "real-message-id-123" not in rendered


def test_trace_sampling_script_prepares_contract_failure_for_review(tmp_path) -> None:
    source = tmp_path / "contract-failure-source.json"
    review_output = tmp_path / "contract-failure-review.json"
    source.write_text(json.dumps(_contract_failure_payload()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/sample_chat_traces.py",
            "--input",
            str(source),
            "--prepare-review-output",
            str(review_output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    review = json.loads(review_output.read_text(encoding="utf-8"))
    assert summary["status"] == "prepared_for_review"
    assert summary["contract_failure_case_count"] == 1
    assert summary["feasible_contract_failure_case_count"] == 1
    assert summary["assisted_probe_case_count"] == 1
    assert summary["historical_raw_case_count"] == 0
    assert review["cases"][0]["trace_kind"] == "output_contract_failure"
    assert review["cases"][0]["replay_stage"] == "post_repair"
    assert review["cases"][0]["expected_output_contract_feasible"] is True
    assert review["cases"][0]["evidence_lane"] == ASSISTED_PROBE_EVIDENCE_LANE
    assert "Ken Haas" not in json.dumps(review)


def test_trace_sampling_script_requires_historical_raw_case(tmp_path) -> None:
    assisted_source = tmp_path / "assisted-source.json"
    historical_source = tmp_path / "historical-source.json"
    rejected_review = tmp_path / "rejected-review.json"
    historical_review = tmp_path / "historical-review.json"
    assisted_source.write_text(
        json.dumps(_contract_failure_payload()),
        encoding="utf-8",
    )
    historical_source.write_text(
        json.dumps(_historical_contract_failure_payload()),
        encoding="utf-8",
    )

    rejected = subprocess.run(
        [
            sys.executable,
            "scripts/sample_chat_traces.py",
            "--input",
            str(assisted_source),
            "--prepare-review-output",
            str(rejected_review),
            "--require-historical-raw",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert rejected.returncode == 2
    assert "trace_sampling_historical_raw_case_required" in rejected.stderr
    assert not rejected_review.exists()

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/sample_chat_traces.py",
            "--input",
            str(historical_source),
            "--prepare-review-output",
            str(historical_review),
            "--require-historical-raw",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(completed.stdout)
    review = json.loads(historical_review.read_text(encoding="utf-8"))
    assert summary["assisted_probe_case_count"] == 0
    assert summary["historical_raw_case_count"] == 1
    assert review["cases"][0]["historical_source_system"] == (
        HISTORICAL_RAW_SOURCE_SYSTEM
    )
    assert review["cases"][0]["historical_selection_method"] == (
        HISTORICAL_RAW_SELECTION_METHOD
    )
    assert review["cases"][0]["historical_operator_attested"] is True


def test_trace_sampling_script_rejects_assisted_export_when_historical_required(
    tmp_path,
) -> None:
    source = tmp_path / "assisted-source.json"
    review_path = tmp_path / "assisted-review.json"
    output = tmp_path / "rejected-corpus.json"
    public_key = tmp_path / "approval-public-key.pem"
    payload = _contract_failure_payload()
    review = prepare_trace_sample_review_artifact(payload)
    source.write_text(json.dumps(payload), encoding="utf-8")
    review_path.write_text(json.dumps(review), encoding="utf-8")
    public_key.write_bytes(_TEST_APPROVAL_PUBLIC_KEY_PEM)

    rejected = subprocess.run(
        [
            sys.executable,
            "scripts/sample_chat_traces.py",
            "--input",
            str(source),
            "--output",
            str(output),
            "--approval-ref",
            "phase31-contract-failure-001",
            "--approved-redacted-content-sha256",
            str(review["redacted_content_sha256"]),
            "--approval-signature",
            _approval_signature(
                "phase31-contract-failure-001",
                str(review["redacted_content_sha256"]),
            ),
            "--approval-public-key",
            str(public_key),
            "--review-artifact",
            str(review_path),
            "--delete-inputs-after-export",
            "--require-historical-raw",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert rejected.returncode == 2
    assert "trace_sampling_historical_raw_case_required" in rejected.stderr
    assert source.exists()
    assert review_path.exists()
    assert not output.exists()


def build_approved_trace_sample_corpus(
    sample_payload: dict[str, object],
    *,
    approval_ref: str,
    existing_corpus: dict[str, object] | None = None,
) -> dict[str, object]:
    review = prepare_trace_sample_review_artifact(sample_payload)
    return _build_approved_trace_sample_corpus(
        sample_payload,
        approval_ref=approval_ref,
        approved_redacted_content_sha256=str(review["redacted_content_sha256"]),
        approval_signature=_approval_signature(
            approval_ref,
            str(review["redacted_content_sha256"]),
        ),
        approval_public_key_pem=_TEST_APPROVAL_PUBLIC_KEY_PEM,
        existing_corpus=existing_corpus,
    )


def _approval_signature(approval_ref: str, digest: str) -> str:
    return base64.b64encode(
        _TEST_APPROVAL_PRIVATE_KEY.sign(
            trace_sample_approval_statement(
                approval_ref=approval_ref,
                redacted_content_sha256=digest,
            )
        )
    ).decode("ascii")


def _sample_payload() -> dict[str, object]:
    return {
        "schema_version": CHAT_TRACE_SAMPLING_WORKFLOW_VERSION,
        "approval": {
            "status": "approved",
            "approval_ref": "phase25-approved-001",
            "purpose": "offline_quality_eval",
            "sensitive_terms_reviewed": True,
            "raw_source_retention": CHAT_TRACE_SAMPLE_RETENTION_POLICY,
        },
        "candidates": [
            {
                "source_trace_id": "real-message-id-123",
                "prompt": "Ken Haas asked for an architecture summary.",
                "requested_model": "auto",
                "internet_mode": "none",
                "memory_context": "[current] Ken Haas prefers concise output.",
                "internet_context": None,
                "response_text": "The architecture uses a deterministic quality gate.",
                "outcome": {
                    "chat_outcome_schema_version": "chat_outcome.v1",
                    "chat_outcome_route_mode": "local",
                    "chat_outcome_quality_action": "accept",
                    "chat_outcome_escalation_rung": "none",
                    "chat_repair_action": "none",
                    "chat_repair_repaired": False,
                    "chat_memory_pack_budget_chars": 6000,
                    "chat_prompt_tool_policy": "no_external_tool_executed",
                },
                "sensitive_terms": ["Ken Haas"],
                "expected_memory_present": "[current]",
                "expected_memory_absent": "[historical]",
            }
        ],
    }


def _contract_failure_payload() -> dict[str, object]:
    return {
        "schema_version": CHAT_TRACE_SAMPLING_WORKFLOW_VERSION,
        "approval": {
            "status": "approved",
            "approval_ref": "phase31-contract-failure-001",
            "purpose": "offline_quality_eval",
            "sensitive_terms_reviewed": True,
            "raw_source_retention": CHAT_TRACE_SAMPLE_RETENTION_POLICY,
        },
        "candidates": [
            {
                "source_trace_id": "phase31-contract-failure-source-001",
                "trace_kind": "output_contract_failure",
                "evidence_lane": ASSISTED_PROBE_EVIDENCE_LANE,
                "prompt": (
                    "Ken Haas asked: Return only a JSON object with key status."
                ),
                "requested_model": "local",
                "internet_mode": "none",
                "memory_context": "[current] Ken Haas prefers exact JSON.",
                "internet_context": None,
                "response_text": "Ken Haas still did not receive JSON.",
                "outcome": {
                    "chat_outcome_schema_version": "chat_outcome.v1",
                    "chat_outcome_route_mode": "local",
                    "chat_outcome_quality_action": "replace_with_safe_fallback",
                    "chat_outcome_escalation_rung": "operator_review",
                    "chat_repair_action": "retry_local_once",
                    "chat_repair_repaired": False,
                    "chat_memory_pack_budget_chars": 6000,
                    "chat_prompt_tool_policy": "no_external_tool_executed",
                    "chat_output_contract_schema_version": "chat_output_contract.v1",
                    "chat_output_contract_applied": True,
                    "chat_output_contract_id": "exact_json",
                    "chat_output_contract_passed": False,
                    "chat_output_contract_issue_count": 1,
                    "chat_output_contract_issues": ["json_object_required"],
                    "chat_output_contract_feasibility_schema_version": (
                        "chat_output_contract_feasibility.v1"
                    ),
                    "chat_output_contract_feasible": True,
                    "chat_output_contract_conflict_count": 0,
                    "chat_output_contract_conflicts": [],
                    "chat_output_contract_preflight_action": "allow_generation",
                },
                "sensitive_terms": ["Ken Haas"],
            }
        ],
    }


def _historical_contract_failure_payload() -> dict[str, object]:
    payload = deepcopy(_contract_failure_payload())
    payload["approval"]["approval_ref"] = "phase36-historical-failure-001"
    candidate = payload["candidates"][0]
    candidate["source_trace_id"] = "phase36-historical-source-001"
    candidate["evidence_lane"] = HISTORICAL_RAW_EVIDENCE_LANE
    candidate["historical_source_system"] = HISTORICAL_RAW_SOURCE_SYSTEM
    candidate["historical_selection_method"] = HISTORICAL_RAW_SELECTION_METHOD
    candidate["historical_operator_attested"] = True
    return payload
