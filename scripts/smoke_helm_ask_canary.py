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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from brain.services.internet_scout.ask_canary import (  # noqa: E402
    DEFAULT_CANARY_CASES,
    AskCanaryCase,
    AskCanarySuiteEvaluation,
    evaluate_ask_canary,
    evaluate_ask_canary_suite,
    parse_sse_payloads,
)

DEFAULT_BASE_URL = "https://jarvis-brain.tail40ed36.ts.net:8186"
DEFAULT_TOKEN_SSH_TARGET = "jarvisbrain@jarvis-brain.tail40ed36.ts.net"
DEFAULT_PROMPT = "Find the official OpenAI API reference URL."


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
        "--token-ssh-target",
        default=os.getenv("HELM_ASK_SMOKE_TOKEN_SSH_TARGET", DEFAULT_TOKEN_SSH_TARGET),
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    token = _smoke_token(
        profile=args.profile,
        base_url=base_url,
        token_ssh_target=args.token_ssh_target,
    )
    if args.suite:
        evaluation = _run_suite(base_url=base_url, token=token)
        print(json.dumps(evaluation.as_dict(), sort_keys=True))
        return 0 if evaluation.passed else 2

    case = AskCanaryCase(name="custom", prompt=args.prompt)
    payloads = _run_case(base_url=base_url, token=token, case=case)
    evaluation = evaluate_ask_canary(payloads, case=case)
    print(json.dumps(evaluation.as_dict(), sort_keys=True))
    return 0 if evaluation.passed else 2


def _run_suite(
    *,
    base_url: str,
    token: str,
) -> AskCanarySuiteEvaluation:
    case_payloads = [
        (case, _run_case(base_url=base_url, token=token, case=case))
        for case in DEFAULT_CANARY_CASES
    ]
    return evaluate_ask_canary_suite(case_payloads)


def _run_case(
    *,
    base_url: str,
    token: str,
    case: AskCanaryCase,
) -> list[dict[str, object]]:
    stream = _call_sse(
        base_url=base_url,
        path="/v1/chat/completions",
        token=token,
        body={
            "messages": [{"role": "user", "content": case.prompt}],
            "model": "auto",
            "internet_mode": "deep_research",
        },
    )
    return parse_sse_payloads(stream)


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
