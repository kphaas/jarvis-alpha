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

from brain.services.internet_scout.ask_canary import (
    evaluate_ask_canary,
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
    stream = _call_sse(
        base_url=base_url,
        path="/v1/chat/completions",
        token=token,
        body={
            "messages": [{"role": "user", "content": args.prompt}],
            "model": "auto",
            "internet_mode": "deep_research",
        },
    )
    payloads = parse_sse_payloads(stream)
    evaluation = evaluate_ask_canary(payloads)
    print(json.dumps(evaluation.as_dict(), sort_keys=True))
    return 0 if evaluation.passed else 2


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
