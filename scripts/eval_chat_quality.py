#!/usr/bin/env python3
"""Run deterministic Alpha chat quality evals."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import sys


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / "common"))

    from brain.services.chat_evaluation_harness import chat_eval_payload
    from brain.services.chat_quality_trends import (
        append_chat_quality_trend_snapshot,
        chat_quality_trend_snapshot,
        load_chat_quality_trend_history,
    )

    history_path = _history_path(args.history_path, repo_root)
    history = (
        load_chat_quality_trend_history(history_path)
        if history_path is not None
        else []
    )
    payload = chat_eval_payload(trend_history=history)
    if args.record_history:
        if history_path is None:
            history_path = repo_root / "logs" / "chat_quality_eval_history.jsonl"
        snapshot = chat_quality_trend_snapshot(
            payload,
            recorded_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
        )
        append_chat_quality_trend_snapshot(history_path, snapshot)
    print(json.dumps(payload, sort_keys=True))
    return 1 if payload["failed"] else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run deterministic Alpha chat quality evals."
    )
    parser.add_argument(
        "--history-path",
        help="Optional JSONL trend history path.",
    )
    parser.add_argument(
        "--record-history",
        action="store_true",
        help="Append a compact metadata-only snapshot after the run.",
    )
    return parser.parse_args()


def _history_path(raw_path: str | None, repo_root: Path) -> Path | None:
    value = raw_path or os.getenv("CHAT_QUALITY_EVAL_HISTORY_PATH")
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else repo_root / path


if __name__ == "__main__":
    sys.exit(main())
