#!/usr/bin/env python3
"""Review and ingest signed, metadata-only chat model benchmark evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    source_path = _outside_repo_path(args.input, repo_root, "input")
    if source_path is None:
        return 2

    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / "common"))
    from brain.services.chat_model_benchmark_evidence import (
        CHAT_MODEL_BENCHMARK_EVIDENCE_SCHEMA_VERSION,
        build_approved_chat_model_benchmark_evidence,
        load_chat_model_benchmark_approval_public_key,
        prepare_chat_model_benchmark_review,
    )

    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        review = prepare_chat_model_benchmark_review(
            payload,
            approval_ref=args.approval_ref,
        )
        if args.prepare_review_output is not None:
            review_path = _outside_repo_path(
                args.prepare_review_output,
                repo_root,
                "review_output",
            )
            if review_path is None or review_path == source_path:
                return _reject("benchmark_evidence_review_output_invalid")
            _atomic_write_json(review_path, review)
            print(
                json.dumps(
                    {
                        "status": "prepared_for_review",
                        "approval_ref": args.approval_ref,
                        "evidence_sha256": review["evidence_sha256"],
                        "approval_statement": review["approval_statement"],
                        "model_count": len(review["benchmark"]["scorecards"]),
                        "raw_prompts_retained": False,
                        "raw_responses_retained": False,
                    },
                    sort_keys=True,
                )
            )
            return 0

        missing = [
            flag
            for flag, value in (
                ("--approved-evidence-sha256", args.approved_evidence_sha256),
                ("--approval-signature", args.approval_signature),
                ("--approval-public-key", args.approval_public_key),
                ("--review-artifact", args.review_artifact),
            )
            if value is None
        ]
        if missing:
            return _reject("benchmark_evidence_required: " + ", ".join(missing))
        review_path = _outside_repo_path(
            args.review_artifact,
            repo_root,
            "review_artifact",
        )
        if review_path is None or review_path == source_path:
            return _reject("benchmark_evidence_review_artifact_invalid")
        approved_review = json.loads(review_path.read_text(encoding="utf-8"))
        if approved_review != review:
            return _reject("benchmark_evidence_review_artifact_mismatch")

        public_key = load_chat_model_benchmark_approval_public_key(
            args.approval_public_key
        )
        store_path = args.store.expanduser()
        if store_path.is_symlink():
            return _reject("benchmark_evidence_store_symlink_not_allowed")
        if not store_path.is_absolute():
            store_path = repo_root / store_path
        store_path = store_path.resolve()
        existing = (
            json.loads(store_path.read_text(encoding="utf-8"))
            if store_path.exists()
            else None
        )
        corpus = build_approved_chat_model_benchmark_evidence(
            payload,
            approval_ref=args.approval_ref,
            approved_evidence_sha256=args.approved_evidence_sha256,
            approval_signature=args.approval_signature,
            approval_public_key_pem=public_key,
            existing_corpus=existing,
        )
        _atomic_write_json(store_path, corpus)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        return _reject(str(exc))

    print(
        json.dumps(
            {
                "status": "ingested",
                "schema_version": CHAT_MODEL_BENCHMARK_EVIDENCE_SCHEMA_VERSION,
                "approval_ref": args.approval_ref,
                "evidence_sha256": args.approved_evidence_sha256,
                "approved_batch_count": len(corpus["batches"]),
                "routing_scores_mutated": False,
                "routing_eligible": False,
            },
            sort_keys=True,
        )
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--approval-ref", required=True)
    parser.add_argument("--prepare-review-output", type=Path)
    parser.add_argument("--review-artifact", type=Path)
    parser.add_argument("--approved-evidence-sha256")
    parser.add_argument("--approval-signature")
    parser.add_argument("--approval-public-key", type=Path)
    parser.add_argument(
        "--store",
        type=Path,
        default=Path(
            os.getenv(
                "ALPHA_CHAT_MODEL_BENCHMARK_EVIDENCE_PATH",
                "logs/chat_model_benchmark_evidence.v1.json",
            )
        ),
    )
    return parser.parse_args()


def _outside_repo_path(path: Path, repo_root: Path, label: str) -> Path | None:
    expanded = path.expanduser()
    if expanded.is_symlink():
        _reject(f"benchmark_evidence_{label}_symlink_not_allowed")
        return None
    resolved = expanded.resolve()
    if resolved.is_relative_to(repo_root):
        _reject(f"benchmark_evidence_{label}_inside_repository")
        return None
    return resolved


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temporary_path = Path(handle.name)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _reject(reason: str) -> int:
    print(json.dumps({"status": "rejected", "reason": reason}), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
