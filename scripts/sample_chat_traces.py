#!/usr/bin/env python3
"""Export operator-approved chat traces into the redacted replay corpus."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import sys
import tempfile


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    source_argument = args.input.expanduser()
    output_argument = args.output.expanduser()
    if source_argument.is_symlink():
        return _reject("trace_sampling_raw_input_symlink_not_allowed")
    if output_argument.is_symlink():
        return _reject("trace_sampling_output_symlink_not_allowed")
    source_path = source_argument.resolve()
    output_path = output_argument
    if not output_path.is_absolute():
        output_path = repo_root / output_path
    output_path = output_path.resolve()

    if source_path.is_relative_to(repo_root):
        return _reject("trace_sampling_raw_input_inside_repository")

    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / "common"))
    from brain.services.chat_redacted_trace_corpus import (
        CHAT_REDACTED_TRACE_CORPUS_SCHEMA_VERSION,
        CHAT_TRACE_SAMPLING_WORKFLOW_VERSION,
        build_approved_trace_sample_corpus,
        load_trace_sample_approval_public_key,
        prepare_trace_sample_review_artifact,
    )

    try:
        sample_payload = json.loads(source_path.read_text(encoding="utf-8"))
        if args.prepare_review_output is not None:
            review_argument = args.prepare_review_output.expanduser()
            if review_argument.is_symlink():
                return _reject("trace_sampling_review_output_symlink_not_allowed")
            review_path = review_argument.resolve()
            if review_path.is_relative_to(repo_root):
                return _reject("trace_sampling_review_output_inside_repository")
            if review_path == source_path:
                return _reject("trace_sampling_review_output_matches_input")
            review_artifact = prepare_trace_sample_review_artifact(sample_payload)
            _atomic_write_json(review_path, review_artifact)
            print(
                json.dumps(
                    {
                        "status": "prepared_for_review",
                        "workflow_version": CHAT_TRACE_SAMPLING_WORKFLOW_VERSION,
                        "redacted_content_sha256": review_artifact[
                            "redacted_content_sha256"
                        ],
                        "approval_statement": review_artifact["approval_statement"],
                        "sampled_case_count": review_artifact["sampled_case_count"],
                        "raw_trace_text_retained": False,
                        "review_artifact_cleanup_required": True,
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.approval_ref is None:
            return _reject("trace_sampling_approval_ref_required")
        if args.approved_redacted_content_sha256 is None:
            return _reject("trace_sampling_approved_digest_required")
        if args.approval_signature is None:
            return _reject("trace_sampling_approval_signature_required")
        if args.approval_public_key is None:
            return _reject("trace_sampling_approval_public_key_required")
        if args.review_artifact is None:
            return _reject("trace_sampling_review_artifact_required")
        if not args.delete_inputs_after_export:
            return _reject("trace_sampling_delete_confirmation_required")
        review_argument = args.review_artifact.expanduser()
        if review_argument.is_symlink():
            return _reject("trace_sampling_review_artifact_symlink_not_allowed")
        review_path = review_argument.resolve()
        if review_path.is_relative_to(repo_root):
            return _reject("trace_sampling_review_artifact_inside_repository")
        if len({source_path, review_path, output_path}) != 3:
            return _reject("trace_sampling_export_paths_must_be_distinct")
        review_artifact = json.loads(review_path.read_text(encoding="utf-8"))
        expected_review_artifact = prepare_trace_sample_review_artifact(sample_payload)
        if review_artifact != expected_review_artifact:
            return _reject("trace_sampling_review_artifact_mismatch")
        approval_public_key_pem = load_trace_sample_approval_public_key(
            args.approval_public_key
        )
        existing_corpus = (
            json.loads(output_path.read_text(encoding="utf-8"))
            if output_path.exists()
            else None
        )
        corpus = build_approved_trace_sample_corpus(
            sample_payload,
            approval_ref=args.approval_ref,
            approved_redacted_content_sha256=(args.approved_redacted_content_sha256),
            approval_signature=args.approval_signature,
            approval_public_key_pem=approval_public_key_pem,
            existing_corpus=existing_corpus,
        )
        sampling_batches = corpus.get("sampling_batches")
        cases = corpus.get("cases")
        if (
            not isinstance(sampling_batches, list)
            or not sampling_batches
            or not isinstance(cases, list)
        ):
            raise ValueError("trace_sampling_export_result_invalid")
        latest_batch = sampling_batches[-1]
        if not isinstance(latest_batch, Mapping):
            raise ValueError("trace_sampling_export_result_invalid")
        _atomic_write_json(output_path, corpus)
        source_path.unlink()
        review_path.unlink()
    except (json.JSONDecodeError, ValueError) as exc:
        return _reject(str(exc))
    except OSError:
        return _reject("trace_sampling_file_operation_failed")

    print(
        json.dumps(
            {
                "status": "exported",
                "schema_version": CHAT_REDACTED_TRACE_CORPUS_SCHEMA_VERSION,
                "workflow_version": CHAT_TRACE_SAMPLING_WORKFLOW_VERSION,
                "approval_ref": args.approval_ref,
                "approved_redacted_content_sha256": latest_batch[
                    "approved_redacted_content_sha256"
                ],
                "approval_key_sha256": latest_batch["approval_key_sha256"],
                "sampled_case_count": latest_batch["sampled_case_count"],
                "corpus_case_count": len(cases),
                "raw_trace_text_retained": False,
                "raw_source_deleted": not source_path.exists(),
                "review_artifact_deleted": not review_path.exists(),
            },
            sort_keys=True,
        )
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Approved raw sample payload outside the repository.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/evals/chat_redacted_trace_corpus.v1.json"),
        help="Redacted corpus output path.",
    )
    parser.add_argument(
        "--approval-ref",
        help="Safe approval reference that must match the input manifest.",
    )
    parser.add_argument(
        "--approved-redacted-content-sha256",
        help="Digest copied from the independently approved review artifact.",
    )
    parser.add_argument(
        "--approval-signature",
        help="Base64 Ed25519 signature over the review artifact approval statement.",
    )
    parser.add_argument(
        "--approval-public-key",
        type=Path,
        help="Ed25519 public key used to verify the detached approval signature.",
    )
    parser.add_argument(
        "--review-artifact",
        type=Path,
        help="Exact redacted review artifact that received operator approval.",
    )
    parser.add_argument(
        "--delete-inputs-after-export",
        action="store_true",
        help="Confirm deletion of the raw source and review artifact after export.",
    )
    parser.add_argument(
        "--prepare-review-output",
        type=Path,
        help="Write the redacted review artifact outside the repository and exit.",
    )
    return parser.parse_args()


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
