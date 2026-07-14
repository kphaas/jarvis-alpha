from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from brain.services.chat_model_task_benchmarks import (
    CHAT_MODEL_TASK_BENCHMARK_VERSION,
    DEFAULT_CHAT_MODEL_BENCHMARK_TASKS,
    chat_model_benchmark_plan,
    run_chat_model_task_benchmarks,
    score_chat_model_task_response,
    validate_chat_model_benchmark_tasks,
)


def test_benchmark_tasks_cover_each_registry_task_class() -> None:
    assert validate_chat_model_benchmark_tasks() == ()
    assert {task.task_class for task in DEFAULT_CHAT_MODEL_BENCHMARK_TASKS} == {
        "fast",
        "grounded",
        "analysis",
        "deep",
    }
    assert all(
        sum(check.weight for check in task.checks) == 100
        for task in DEFAULT_CHAT_MODEL_BENCHMARK_TASKS
    )


def test_response_scoring_is_objective_and_metadata_only() -> None:
    task = next(
        task
        for task in DEFAULT_CHAT_MODEL_BENCHMARK_TASKS
        if task.task_id == "grounded_evidence_only"
    )
    result = score_chat_model_task_response(
        route_mode="local",
        task_id=task.task_id,
        response_text=task.reference_response,
        latency_ms=12,
    )
    payload = result.metadata()

    assert result.passed is True
    assert result.score == 100
    assert payload["benchmark_version"] == CHAT_MODEL_TASK_BENCHMARK_VERSION
    assert payload["model_id"] == "llama3.1:8b"
    assert payload["raw_response_retained"] is False
    assert task.reference_response not in json.dumps(payload)


def test_bad_response_fails_without_retaining_adapter_error() -> None:
    result = score_chat_model_task_response(
        route_mode="claude",
        task_id="analysis_bounded_tradeoff",
        response_text="Option A.",
        latency_ms=-1,
        error_code="secret provider detail",
    )

    assert result.passed is False
    assert result.latency_ms == 0
    assert result.error_code == "model_call_failed"
    assert result.response_sha256


def test_plan_is_zero_call_and_does_not_include_prompts() -> None:
    payload = chat_model_benchmark_plan(route_modes=("local", "claude"))
    rendered = json.dumps(payload)

    assert payload["status"] == "planned"
    assert payload["planned_model_calls"] == 8
    assert payload["reporting"]["model_calls"] == 0
    assert payload["routing_scores_mutated"] is False
    assert "Project Atlas deployment is paused" not in rendered


def test_runner_returns_per_model_scorecards_and_sanitizes_exceptions() -> None:
    references = {
        task.task_id: task.reference_response
        for task in DEFAULT_CHAT_MODEL_BENCHMARK_TASKS
    }
    prompts = {task.prompt: task.task_id for task in DEFAULT_CHAT_MODEL_BENCHMARK_TASKS}

    async def invoke(prompt: str, route_mode: str) -> dict[str, object]:
        if route_mode == "claude":
            raise RuntimeError("secret provider detail")
        return {
            "result": references[prompts[prompt]],
            "mode": "local",
            "chat_model_id": "llama3.1:8b",
        }

    ticks = iter(range(0, 100_000_000, 1_000_000))
    payload = asyncio.run(
        run_chat_model_task_benchmarks(
            route_modes=("local", "claude"),
            invoke=invoke,
            timer_ns=lambda: next(ticks),
        )
    )
    rendered = json.dumps(payload)

    assert payload["reporting"]["model_calls"] == 8
    assert len(payload["scorecards"]) == 2
    assert payload["scorecards"][0]["average_score"] == 100.0
    assert payload["scorecards"][1]["average_score"] < 100
    assert "secret provider detail" not in rendered
    assert payload["advisory_only"] is True


def test_runner_fails_closed_on_model_identity_mismatch() -> None:
    task = DEFAULT_CHAT_MODEL_BENCHMARK_TASKS[0]

    async def invoke(_prompt: str, _route_mode: str) -> dict[str, object]:
        return {
            "result": task.reference_response,
            "mode": "local",
            "chat_model_id": "unexpected-model",
        }

    ticks = iter((0, 1_000_000))
    payload = asyncio.run(
        run_chat_model_task_benchmarks(
            route_modes=("local",),
            task_ids=(task.task_id,),
            invoke=invoke,
            timer_ns=lambda: next(ticks),
        )
    )

    assert payload["status"] == "failed"
    assert payload["results"][0]["error_code"] == "model_identity_mismatch"
    assert payload["results"][0]["passed"] is False


def test_benchmark_script_defaults_to_dry_run() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/benchmark_chat_models.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["planned_model_calls"] == 16
    assert payload["reporting"]["model_calls"] == 0
    assert payload["status"] == "planned"


def test_benchmark_script_refuses_unacknowledged_paid_calls() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/benchmark_chat_models.py",
            "--live",
            "--models",
            "claude",
            "--max-calls",
            "4",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "--allow-paid-models" in completed.stderr


def test_benchmark_script_refuses_calls_above_operator_cap() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/benchmark_chat_models.py",
            "--live",
            "--models",
            "local",
            "--max-calls",
            "3",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "planned calls (4) exceed --max-calls (3)" in completed.stderr


def test_router_import_does_not_require_database_configuration() -> None:
    repo_root = Path.cwd()
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "ALPHA_DB_DSN",
            "ALPHA_DB_DSN_WRITER",
            "ALPHA_DB_DSN_BUDDY",
            "ALPHA_GATEWAY_URL",
        }
    }
    env["PYTHONPATH"] = os.pathsep.join(
        (str(repo_root), str(repo_root / "common"), env.get("PYTHONPATH", ""))
    )

    completed = subprocess.run(
        [sys.executable, "-c", "import brain.routing.router"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
