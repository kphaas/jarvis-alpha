from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from brain.services.chat_model_benchmark_evidence import (
    build_approved_chat_model_benchmark_evidence,
    chat_model_benchmark_comparison,
    load_chat_model_benchmark_evidence,
    prepare_chat_model_benchmark_review,
)
from brain.services.chat_model_task_benchmarks import (
    DEFAULT_CHAT_MODEL_BENCHMARK_TASKS,
    chat_model_task_benchmark_payload,
    score_chat_model_task_response,
)

APPROVAL_REF = "phase28-local-20260714"
RUN_COMPLETED_AT = "2026-07-14T13:26:53+00:00"


def _benchmark_payload() -> dict[str, object]:
    results = [
        score_chat_model_task_response(
            route_mode="local",
            task_id=task.task_id,
            response_text=task.reference_response,
            latency_ms=index + 10,
        )
        for index, task in enumerate(DEFAULT_CHAT_MODEL_BENCHMARK_TASKS)
    ]
    payload = chat_model_task_benchmark_payload(results, model_calls=len(results))
    payload["run_completed_at"] = RUN_COMPLETED_AT
    return payload


def _keys() -> tuple[Ed25519PrivateKey, bytes]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, public_key


def _approved_corpus() -> tuple[dict[str, object], bytes]:
    payload = _benchmark_payload()
    review = prepare_chat_model_benchmark_review(
        payload,
        approval_ref=APPROVAL_REF,
    )
    private_key, public_key = _keys()
    signature = base64.b64encode(
        private_key.sign(str(review["approval_statement"]).encode("ascii"))
    ).decode("ascii")
    corpus = build_approved_chat_model_benchmark_evidence(
        payload,
        approval_ref=APPROVAL_REF,
        approved_evidence_sha256=str(review["evidence_sha256"]),
        approval_signature=signature,
        approval_public_key_pem=public_key,
    )
    return corpus, public_key


def test_approved_evidence_is_metadata_only_and_never_routing_eligible(
    tmp_path: Path,
) -> None:
    corpus, public_key = _approved_corpus()
    store = tmp_path / "evidence.json"
    store.write_text(json.dumps(corpus), encoding="utf-8")

    loaded = load_chat_model_benchmark_evidence(
        store,
        approval_public_key_pem=public_key,
    )
    comparison = chat_model_benchmark_comparison(loaded)
    rendered = json.dumps(loaded)

    assert comparison["status"] == "ready"
    assert comparison["approved_batch_count"] == 1
    assert comparison["routing_eligible"] is False
    assert comparison["routing_scores_mutated"] is False
    assert comparison["models"][0]["model_id"] == "llama3.1:8b"
    assert comparison["models"][0]["tasks"]["fast"]["score"] == 100
    assert "Project Atlas deployment is paused" not in rendered


def test_evidence_rejects_raw_retention_and_inconsistent_scorecards() -> None:
    payload = _benchmark_payload()
    payload["reporting"]["raw_responses_retained"] = True

    with pytest.raises(
        ValueError,
        match="benchmark_evidence_raw_response_retention_not_allowed",
    ):
        prepare_chat_model_benchmark_review(payload, approval_ref=APPROVAL_REF)

    payload = _benchmark_payload()
    payload["scorecards"][0]["average_score"] = 1
    with pytest.raises(ValueError, match="benchmark_evidence_scorecard_mismatch"):
        prepare_chat_model_benchmark_review(payload, approval_ref=APPROVAL_REF)

    payload = _benchmark_payload()
    payload["results"][0]["score"] = 0
    with pytest.raises(ValueError, match="benchmark_evidence_score_mismatch"):
        prepare_chat_model_benchmark_review(payload, approval_ref=APPROVAL_REF)


def test_evidence_rejects_invalid_signature_and_duplicate_approval() -> None:
    payload = _benchmark_payload()
    review = prepare_chat_model_benchmark_review(payload, approval_ref=APPROVAL_REF)
    _, public_key = _keys()

    with pytest.raises(
        ValueError,
        match="benchmark_evidence_approval_signature_invalid",
    ):
        build_approved_chat_model_benchmark_evidence(
            payload,
            approval_ref=APPROVAL_REF,
            approved_evidence_sha256=str(review["evidence_sha256"]),
            approval_signature=base64.b64encode(b"not-a-signature").decode("ascii"),
            approval_public_key_pem=public_key,
        )

    corpus, public_key = _approved_corpus()
    batch = corpus["batches"][0]
    with pytest.raises(
        ValueError,
        match="benchmark_evidence_approval_ref_duplicate",
    ):
        build_approved_chat_model_benchmark_evidence(
            payload,
            approval_ref=APPROVAL_REF,
            approved_evidence_sha256=str(batch["evidence_sha256"]),
            approval_signature=str(batch["approval_signature"]),
            approval_public_key_pem=public_key,
            existing_corpus=corpus,
        )


def test_ingestion_cli_requires_reviewed_detached_signature(tmp_path: Path) -> None:
    source = tmp_path / "benchmark.json"
    review_path = tmp_path / "review.json"
    public_key_path = tmp_path / "approval.pub"
    store = tmp_path / "evidence.json"
    source.write_text(json.dumps(_benchmark_payload()), encoding="utf-8")

    prepared = subprocess.run(
        [
            sys.executable,
            "scripts/ingest_chat_model_benchmarks.py",
            "--input",
            str(source),
            "--approval-ref",
            APPROVAL_REF,
            "--prepare-review-output",
            str(review_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    prepared_payload = json.loads(prepared.stdout)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    private_key, public_key = _keys()
    public_key_path.write_bytes(public_key)
    signature = base64.b64encode(
        private_key.sign(str(review["approval_statement"]).encode("ascii"))
    ).decode("ascii")

    ingested = subprocess.run(
        [
            sys.executable,
            "scripts/ingest_chat_model_benchmarks.py",
            "--input",
            str(source),
            "--approval-ref",
            APPROVAL_REF,
            "--review-artifact",
            str(review_path),
            "--approved-evidence-sha256",
            prepared_payload["evidence_sha256"],
            "--approval-signature",
            signature,
            "--approval-public-key",
            str(public_key_path),
            "--store",
            str(store),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(ingested.stdout)["routing_eligible"] is False
    assert json.loads(store.read_text(encoding="utf-8"))["batches"]
