#!/usr/bin/env python3
"""Generate a sanitized Spark voice-profile proposal."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_ROOT = REPO_ROOT / "common"
for import_root in (str(REPO_ROOT), str(COMMON_ROOT)):
    if import_root not in sys.path:
        sys.path.insert(0, import_root)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a sanitized Spark voice-profile proposal."
    )
    parser.add_argument(
        "--vault-root",
        default=(
            os.environ.get("SPARK_PERSONALITY_VAULT")
            or os.environ.get("JARVIS_PERSONALITY_VAULT")
            or "~/jarvis-personality"
        ),
        help="Path to jarvis-personality. Defaults to ~/jarvis-personality.",
    )
    parser.add_argument("--principal", default="ken")
    parser.add_argument(
        "--live-gmail",
        action="store_true",
        help="Read approved sent-mail bodies and emit sanitized statistics only.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path. Stdout is used when omitted.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON instead of pretty-printed JSON.",
    )
    return parser


async def _run(args: argparse.Namespace) -> str:
    from brain.services.spark_voice_ingest import build_spark_voice_profile_proposal

    if args.live_gmail:
        from brain.services.gmail_client import GmailClient

        gmail_client = GmailClient()
    else:
        gmail_client = None

    proposal = await build_spark_voice_profile_proposal(
        vault_root=args.vault_root,
        principal_id=args.principal,
        gmail_client=gmail_client,
        live_gmail=args.live_gmail,
    )
    return proposal.to_json(indent=None if args.compact else 2)


def main() -> None:
    args = _parser().parse_args()
    payload = asyncio.run(_run(args))
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
        return
    print(payload)


if __name__ == "__main__":
    main()
