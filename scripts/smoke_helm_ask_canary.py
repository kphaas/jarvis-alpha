#!/usr/bin/env python3
"""Smoke Helm Ask's Beacon-backed web path without printing secrets."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_ROOT = REPO_ROOT / "common"
for path in (REPO_ROOT, COMMON_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from brain.services.internet_scout.ask_canary import (  # noqa: E402
    DEFAULT_CANARY_CASES,
    EXTENDED_CANARY_CASES,
    AskCanaryCase,
    AskCanarySuiteEvaluation,
    evaluate_ask_canary,
    evaluate_ask_canary_suite,
    parse_sse_payloads,
)

DEFAULT_BASE_URL = "https://jarvis-brain.tail40ed36.ts.net:8186"
DEFAULT_TOKEN_SSH_TARGET = "jarvisbrain@jarvis-brain.tail40ed36.ts.net"
DEFAULT_PROMPT = "Find the official OpenAI API reference URL."
DEFAULT_CANARY_PROJECT_ID = 1644


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", default=os.getenv("ALPHA_BASE_URL", DEFAULT_BASE_URL)
    )
    parser.add_argument("--profile", default=os.getenv("HELM_ASK_SMOKE_PROFILE", "ken"))
    parser.add_argument(
        "--prompt",
        default=os.getenv("HELM_ASK_SMOKE_PROMPT", DEFAULT_PROMPT),
    )
    parser.add_argument(
        "--suite",
        action="store_true",
        default=os.getenv("HELM_ASK_SMOKE_SUITE", "").lower() in {"1", "true", "yes"},
        help="run the default Beacon Ask canary suite",
    )
    parser.add_argument(
        "--extended",
        action="store_true",
        default=os.getenv("HELM_ASK_SMOKE_EXTENDED", "").lower()
        in {"1", "true", "yes"},
        help="include slower multi-source research quality canaries",
    )
    parser.add_argument(
        "--token-ssh-target",
        default=os.getenv("HELM_ASK_SMOKE_TOKEN_SSH_TARGET", DEFAULT_TOKEN_SSH_TARGET),
    )
    parser.add_argument(
        "--thread-id",
        default=os.getenv("HELM_ASK_SMOKE_THREAD_ID"),
        help="reuse a known Ask thread UUID",
    )
    parser.add_argument(
        "--project-id",
        type=_optional_int,
        default=_optional_int(
            os.getenv(
                "HELM_ASK_SMOKE_PROJECT_ID",
                str(DEFAULT_CANARY_PROJECT_ID),
            )
        ),
        help="project scope for reusable canary threads; set to none to disable",
    )
    parser.add_argument(
        "--keep-thread",
        action="store_true",
        default=os.getenv("HELM_ASK_SMOKE_KEEP_THREAD", "").lower()
        in {"1", "true", "yes"},
        help="keep the generated canary thread for manual inspection",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    token = _smoke_token(
        profile=args.profile,
        base_url=base_url,
        token_ssh_target=args.token_ssh_target,
    )
    if args.suite or args.extended:
        cases = DEFAULT_CANARY_CASES + (EXTENDED_CANARY_CASES if args.extended else ())
        suite_thread_ids: list[str] = []
        try:
            evaluation, suite_thread_ids = _run_suite(
                base_url=base_url,
                token=token,
                cases=cases,
                thread_id=args.thread_id,
                project_id=args.project_id,
                archive_case_threads=not args.thread_id and not args.keep_thread,
            )
        finally:
            if suite_thread_ids and not args.thread_id and not args.keep_thread:
                try:
                    _archive_threads(
                        base_url=base_url,
                        token=token,
                        thread_ids=suite_thread_ids,
                    )
                except Exception as exc:
                    print(
                        f"warning: failed to archive canary thread(s): {exc}",
                        file=sys.stderr,
                    )
        print(json.dumps(evaluation.as_dict(), sort_keys=True))
        return 0 if evaluation.passed else 2

    case = AskCanaryCase(name="custom", prompt=args.prompt)
    payloads = _run_case(
        base_url=base_url,
        token=token,
        case=case,
        thread_id=args.thread_id,
        project_id=args.project_id,
    )
    evaluation = evaluate_ask_canary(payloads, case=case)
    print(json.dumps(evaluation.as_dict(), sort_keys=True))
    return 0 if evaluation.passed else 2


def _run_suite(
    *,
    base_url: str,
    token: str,
    cases: tuple[AskCanaryCase, ...],
    thread_id: str | None,
    project_id: int | None,
    archive_case_threads: bool = False,
) -> tuple[AskCanarySuiteEvaluation, list[str]]:
    case_payloads: list[tuple[AskCanaryCase, list[dict[str, object]]]] = []
    created_thread_ids: list[str] = []
    for case in cases:
        payloads = _run_case(
            base_url=base_url,
            token=token,
            case=case,
            thread_id=thread_id,
            project_id=project_id,
        )
        if thread_id is None:
            payload_thread_id = _thread_id_from_payloads(payloads)
            if payload_thread_id:
                if archive_case_threads:
                    _archive_thread(
                        base_url=base_url,
                        token=token,
                        thread_id=payload_thread_id,
                    )
                else:
                    created_thread_ids.append(payload_thread_id)
        case_payloads.append((case, payloads))
    return evaluate_ask_canary_suite(case_payloads), created_thread_ids


def _run_case(
    *,
    base_url: str,
    token: str,
    case: AskCanaryCase,
    thread_id: str | None,
    project_id: int | None,
) -> list[dict[str, object]]:
    body: dict[str, object] = {
        "messages": [{"role": "user", "content": case.prompt}],
        "model": "auto",
        "internet_mode": case.request_mode,
    }
    if thread_id:
        body["thread_id"] = thread_id
    if project_id is not None:
        body["project_id"] = project_id

    stream = _call_sse(
        base_url=base_url,
        path="/v1/chat/completions",
        token=token,
        body=body,
    )
    return parse_sse_payloads(stream)


def _thread_id_from_payloads(payloads: list[dict[str, object]]) -> str | None:
    for payload in reversed(payloads):
        thread_id = payload.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            return thread_id
    return None


def _smoke_token(
    *,
    profile: str,
    base_url: str,
    token_ssh_target: str | None,
) -> str:
    token = os.getenv("HELM_ASK_SMOKE_TOKEN") or os.getenv("BEACON_SMOKE_TOKEN")
    if token:
        return token

    if _is_local_base_url(base_url):
        return _local_smoke_token(profile=profile)

    if token_ssh_target:
        generated = subprocess.check_output(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "StrictHostKeyChecking=no",
                token_ssh_target,
                "cd ~/jarvis-alpha && .venv/bin/python scripts/gen_test_token.py "
                f"{shlex.quote(profile)}",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if generated:
            return generated

    raise RuntimeError(
        "set HELM_ASK_SMOKE_TOKEN or HELM_ASK_SMOKE_TOKEN_SSH_TARGET for Ask canary"
    )


def _local_smoke_token(*, profile: str) -> str:
    repo_root = Path(__file__).resolve().parents[1]
    python_bin = os.getenv("PYTHON_BIN", str(repo_root / ".venv/bin/python"))
    generated = subprocess.check_output(
        [python_bin, str(repo_root / "scripts/gen_test_token.py"), profile],
        text=True,
        stderr=subprocess.DEVNULL,
    ).strip()
    if not generated:
        raise RuntimeError("test token generation returned no token")
    return generated


def _is_local_base_url(base_url: str) -> bool:
    return (
        "://localhost" in base_url
        or "://127.0.0.1" in base_url
        or "://[::1]" in base_url
    )


def _optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    clean_value = value.strip().lower()
    if clean_value in {"", "none", "null", "off", "false", "0"}:
        return None
    return int(clean_value)


def _archive_thread(
    *,
    base_url: str,
    token: str,
    thread_id: str,
) -> None:
    request = urllib.request.Request(
        f"{base_url}/v1/threads/{thread_id}",
        method="DELETE",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(
        request,
        context=ssl._create_unverified_context(),
        timeout=30,
    ):
        return


def _archive_threads(
    *,
    base_url: str,
    token: str,
    thread_ids: list[str],
) -> None:
    for thread_id in dict.fromkeys(thread_ids):
        _archive_thread(
            base_url=base_url,
            token=token,
            thread_id=thread_id,
        )


def _call_sse(
    *,
    base_url: str,
    path: str,
    token: str,
    body: dict[str, object],
) -> str:
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(
            request,
            context=ssl._create_unverified_context(),
            timeout=90,
        ) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"POST {path} failed: HTTP {exc.code} {detail}") from exc


if __name__ == "__main__":
    sys.exit(main())
