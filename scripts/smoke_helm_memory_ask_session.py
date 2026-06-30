#!/usr/bin/env python3
"""Smoke Ask's authenticated memory-recall path without printing secrets."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from smoke_helm_ask_canary import (  # noqa: E402
    DEFAULT_BASE_URL,
    DEFAULT_CANARY_PROJECT_ID,
    DEFAULT_TOKEN_SSH_TARGET,
    _archive_thread,
    _optional_int,
    _run_case,
    _smoke_token,
    _thread_id_from_payloads,
)
from brain.services.internet_scout.ask_canary import AskCanaryCase  # noqa: E402

BEACON_INSUFFICIENT_MODEL = "beacon/insufficient-evidence"
DEFAULT_PROMPT = (
    "What current Ken career/profile facts are in memory? Use only approved "
    "memory. Answer in 3 short bullets. Prefix each bullet with Memory: and "
    "label anything old as historical."
)
FORBIDDEN_FALLBACK_PHRASES = (
    "i need to verify",
    "need to verify",
    "use web search",
    "web verification",
    "turn on web search",
    "beacon needs",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv(
            "HELM_MEMORY_ASK_SMOKE_BASE_URL",
            os.getenv("ALPHA_BASE_URL", DEFAULT_BASE_URL),
        ),
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("HELM_MEMORY_ASK_SMOKE_PROFILE", "ken"),
    )
    parser.add_argument(
        "--prompt",
        default=os.getenv("HELM_MEMORY_ASK_SMOKE_PROMPT", DEFAULT_PROMPT),
    )
    parser.add_argument(
        "--token-ssh-target",
        default=os.getenv(
            "HELM_MEMORY_ASK_SMOKE_TOKEN_SSH_TARGET",
            os.getenv("HELM_ASK_SMOKE_TOKEN_SSH_TARGET", DEFAULT_TOKEN_SSH_TARGET),
        ),
    )
    parser.add_argument(
        "--thread-id",
        default=os.getenv("HELM_MEMORY_ASK_SMOKE_THREAD_ID"),
        help="reuse a known Ask thread UUID",
    )
    parser.add_argument(
        "--project-id",
        type=_optional_int,
        default=_optional_int(
            os.getenv(
                "HELM_MEMORY_ASK_SMOKE_PROJECT_ID",
                str(DEFAULT_CANARY_PROJECT_ID),
            )
        ),
        help="project scope for reusable smoke threads; set to none to disable",
    )
    parser.add_argument(
        "--keep-thread",
        action="store_true",
        default=os.getenv("HELM_MEMORY_ASK_SMOKE_KEEP_THREAD", "").lower()
        in {"1", "true", "yes"},
        help="keep the generated smoke thread for manual inspection",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    token = _smoke_token(
        profile=args.profile,
        base_url=base_url,
        token_ssh_target=args.token_ssh_target,
    )
    case = AskCanaryCase(
        name="ken_current_profile_memory_recall",
        prompt=args.prompt,
        request_mode="none",
        require_supported_evidence=False,
        require_memory_boundary=False,
        require_synthesis_behavior=None,
    )
    payloads = _run_case(
        base_url=base_url,
        token=token,
        case=case,
        thread_id=args.thread_id,
        project_id=args.project_id,
    )
    result = evaluate_memory_ask_payloads(payloads)
    thread_id = _thread_id_from_payloads(payloads)
    result["thread_id"] = thread_id

    if thread_id and not args.thread_id and not args.keep_thread:
        try:
            _archive_thread(base_url=base_url, token=token, thread_id=thread_id)
            result["thread_archived"] = True
        except Exception as exc:
            result["thread_archived"] = False
            result["archive_warning"] = type(exc).__name__

    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 2


def evaluate_memory_ask_payloads(
    payloads: list[dict[str, object]],
) -> dict[str, object]:
    answer_text = "".join(
        str(payload.get("delta", ""))
        for payload in payloads
        if payload.get("done") is not True
    )
    answer_lower = answer_text.lower()
    models = {
        str(payload.get("model", ""))
        for payload in payloads
        if isinstance(payload.get("model"), str)
    }
    web_suggestion_payloads = [
        payload for payload in payloads if "web_suggestion_mode" in payload
    ]
    internet_payloads = [payload for payload in payloads if "internet_mode" in payload]
    checks = {
        "stream_returned_answer": bool(answer_text.strip()),
        "beacon_insufficient_model_absent": BEACON_INSUFFICIENT_MODEL not in models,
        "web_suggestion_metadata_absent": not web_suggestion_payloads,
        "internet_metadata_absent": not internet_payloads,
        "web_fallback_copy_absent": not any(
            phrase in answer_lower for phrase in FORBIDDEN_FALLBACK_PHRASES
        ),
        "memory_labeled_answer": "memory:" in answer_lower,
        "ken_profile_answer": "ken" in answer_lower,
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "suite": "helm_memory_ask_session",
        "status": "failed" if failures else "passed",
        "checks": checks,
        "failures": failures,
        "answer_preview": answer_text[:320],
    }


if __name__ == "__main__":
    sys.exit(main())
