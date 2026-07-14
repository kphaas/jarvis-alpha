#!/usr/bin/env python3
"""Plan or run the advisory Alpha per-model task benchmark lane."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
from pathlib import Path
import sys


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / "common"))

    from brain.routing.model_capability_registry import (
        DEFAULT_CHAT_MODEL_CAPABILITIES,
    )
    from brain.services.chat_model_task_benchmarks import (
        chat_model_benchmark_plan,
        run_chat_model_task_benchmarks,
    )

    route_modes = args.models or tuple(
        capability.route_mode for capability in DEFAULT_CHAT_MODEL_CAPABILITIES
    )
    try:
        plan = chat_model_benchmark_plan(
            route_modes=route_modes,
            task_ids=args.tasks,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if not args.live:
        _emit(plan, args.output)
        return 0
    if not args.models:
        raise SystemExit("--live requires explicit --models selection")
    if plan["planned_model_calls"] > args.max_calls:
        raise SystemExit(
            f"planned calls ({plan['planned_model_calls']}) exceed --max-calls "
            f"({args.max_calls})"
        )
    paid_routes = [
        str(model["route_mode"])
        for model in plan["models"]
        if int(model["cost_tier"]) > 0
    ]
    if paid_routes and not args.allow_paid_models:
        raise SystemExit(
            "paid/cloud routes require --allow-paid-models: " + ", ".join(paid_routes)
        )

    from brain.routing.router import route

    async def invoke(prompt: str, route_mode: str) -> dict[str, object]:
        return await route(prompt, mode=route_mode)

    payload = asyncio.run(
        run_chat_model_task_benchmarks(
            route_modes=route_modes,
            task_ids=args.tasks,
            invoke=invoke,
        )
    )
    payload["run_completed_at"] = datetime.now(UTC).isoformat()
    _emit(payload, args.output)
    return 1 if payload["failed"] else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plan a metadata-only model benchmark, or explicitly run bounded model "
            "calls. Live results never mutate routing scores."
        )
    )
    parser.add_argument(
        "--models",
        nargs="+",
        help="Explicit route modes such as local, claude, gemini, or perplexity.",
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        help="Optional benchmark task IDs; defaults to all four task classes.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute model calls. Without this flag, only a zero-call plan is emitted.",
    )
    parser.add_argument(
        "--allow-paid-models",
        action="store_true",
        help="Explicitly acknowledge paid/brokered/cloud calls selected with --live.",
    )
    parser.add_argument(
        "--max-calls",
        type=_positive_int,
        default=4,
        help="Hard live-call cap (default: 4).",
    )
    parser.add_argument(
        "--output",
        help="Optional path for the compact metadata-only JSON result.",
    )
    return parser.parse_args()


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 64:
        raise argparse.ArgumentTypeError("must be between 1 and 64")
    return parsed


def _emit(payload: dict[str, object], raw_path: str | None) -> None:
    rendered = json.dumps(payload, sort_keys=True)
    if raw_path:
        path = Path(raw_path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    sys.exit(main())
