#!/usr/bin/env python3
"""Plan or run the bounded local output-contract benchmark."""

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

    from brain.services.chat_local_output_benchmark import (
        local_output_benchmark_plan,
        local_output_benchmark_tasks,
        run_local_output_contract_benchmark,
    )

    try:
        tasks = local_output_benchmark_tasks(args.profile)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    plan = local_output_benchmark_plan(
        tasks,
        samples=args.samples,
        profile=args.profile,
    )
    if not args.live:
        _emit(plan, args.output)
        return 0
    if int(plan["planned_max_calls"]) > args.max_calls:
        raise SystemExit(
            f"maximum calls ({plan['planned_max_calls']}) exceed --max-calls "
            f"({args.max_calls})"
        )

    from brain.routing.generation_policy import ChatGenerationPolicy
    from brain.routing.router import route

    async def invoke(
        prompt: str,
        route_mode: str,
        generation_policy: ChatGenerationPolicy,
    ) -> dict[str, object]:
        if route_mode != "local":
            raise RuntimeError("local output benchmark forbids non-local routes")
        return await route(
            prompt,
            mode="local",
            generation_policy=generation_policy,
        )

    payload = asyncio.run(
        run_local_output_contract_benchmark(
            invoke=invoke,
            tasks=tasks,
            samples=args.samples,
            profile=args.profile,
        )
    )
    payload["run_completed_at"] = datetime.now(UTC).isoformat()
    _emit(payload, args.output)
    return 0 if payload["status"] == "passed" else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or run the local-only Phase 30 deterministic-output benchmark. "
            "The repeated-run stability gate is advisory and never mutates routing."
        )
    )
    parser.add_argument(
        "--profile",
        default="baseline",
        help="Reviewed task profile: baseline or adversarial (default: baseline).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute local Ollama calls; the default emits a zero-call plan.",
    )
    parser.add_argument(
        "--samples",
        type=_sample_count,
        default=3,
        help="Serial samples per task for the stability gate (default: 3).",
    )
    parser.add_argument(
        "--max-calls",
        type=_call_cap,
        default=24,
        help="Hard call cap including one possible repair per sample (default: 24).",
    )
    parser.add_argument(
        "--output",
        help="Optional path for the metadata-only JSON result.",
    )
    return parser.parse_args()


def _sample_count(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 5:
        raise argparse.ArgumentTypeError("must be between 1 and 5")
    return parsed


def _call_cap(value: str) -> int:
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
