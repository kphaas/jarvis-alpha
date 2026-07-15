from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from brain.services.chat_model_task_benchmarks import (
    CHAT_MODEL_TASK_BENCHMARK_VERSION,
    DEFAULT_CHAT_MODEL_BENCHMARK_TASKS,
    chat_model_benchmark_plan,
    run_chat_model_task_benchmarks,
    score_chat_model_task_response,
    validate_chat_model_benchmark_tasks,
)
from brain.services.chat_local_output_benchmark import (
    ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_PROFILE,
    ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_TASKS,
    CHAT_LOCAL_OUTPUT_BENCHMARK_PROFILE_VERSION,
    CHAT_LOCAL_OUTPUT_BENCHMARK_SCHEMA_VERSION,
    run_local_output_contract_benchmark,
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


def test_local_output_contract_benchmark_repairs_each_task_once() -> None:
    calls: list[str] = []

    async def invoke(
        prompt: str,
        route_mode: str,
        generation_policy: object,
    ) -> dict[str, object]:
        calls.append(prompt)
        assert getattr(generation_policy, "deterministic") is True
        task = next(
            task for task in DEFAULT_CHAT_MODEL_BENCHMARK_TASKS if task.prompt in prompt
        )
        response = task.reference_response if prompt.startswith("Repair") else "bad"
        return {
            "result": response,
            "mode": route_mode,
            "chat_model_id": "llama3.1:8b",
            "chat_deterministic_decoding_applied": True,
            "chat_structured_output_applied": bool(
                getattr(generation_policy, "json_mode")
            ),
            "chat_exact_key_schema_applied": bool(
                getattr(generation_policy, "exact_json_keys")
            ),
        }

    payload = asyncio.run(run_local_output_contract_benchmark(invoke=invoke))
    rendered = json.dumps(payload)

    assert payload["schema_version"] == CHAT_LOCAL_OUTPUT_BENCHMARK_SCHEMA_VERSION
    assert payload["status"] == "passed"
    assert payload["passed"] == 12
    assert payload["reporting"]["model_calls"] == 24
    assert payload["reporting"]["repair_attempts"] == 12
    assert all(row["repair_attempted"] for row in payload["results"])
    assert all(row["score"] == 100 for row in payload["results"])
    assert all(row["chat_output_contract_passed"] for row in payload["results"])
    assert all(
        row["chat_exact_key_schema_applied"]
        for row in payload["results"]
        if row["task_id"] == "fast_exact_json"
    )
    assert payload["stability"]["fully_passing_samples"] == 3
    assert payload["stability"]["stable_tasks"] == 4
    assert payload["stability"]["gate_passed"] is True
    assert "Project Atlas is paused" not in rendered


def test_local_output_contract_script_defaults_to_zero_call_plan() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/benchmark_local_output_contract.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["status"] == "planned"
    assert payload["profile"] == "baseline"
    assert payload["profile_version"] == CHAT_LOCAL_OUTPUT_BENCHMARK_PROFILE_VERSION
    assert payload["local_only"] is True
    assert payload["samples"] == 3
    assert payload["planned_initial_calls"] == 12
    assert payload["planned_max_calls"] == 24
    assert payload["reporting"]["model_calls"] == 0


def test_adversarial_local_output_profile_passes_reviewed_references() -> None:
    assert len(ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_TASKS) == 8
    assert {task.task_class for task in ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_TASKS} == {
        "fast",
        "grounded",
        "analysis",
        "deep",
    }

    async def invoke(
        prompt: str,
        route_mode: str,
        generation_policy: object,
    ) -> dict[str, object]:
        task = next(
            task
            for task in ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_TASKS
            if task.prompt in prompt
        )
        return {
            "result": task.reference_response,
            "mode": route_mode,
            "chat_model_id": "llama3.1:8b",
            "chat_deterministic_decoding_applied": True,
            "chat_structured_output_applied": bool(
                getattr(generation_policy, "json_mode")
            ),
            "chat_exact_key_schema_applied": bool(
                getattr(generation_policy, "exact_json_keys")
            ),
        }

    payload = asyncio.run(
        run_local_output_contract_benchmark(
            invoke=invoke,
            tasks=ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_TASKS,
            samples=1,
            profile=ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_PROFILE,
        )
    )
    rendered = json.dumps(payload)

    assert payload["status"] == "passed"
    assert payload["profile"] == ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_PROFILE
    assert payload["profile_version"] == CHAT_LOCAL_OUTPUT_BENCHMARK_PROFILE_VERSION
    assert payload["passed"] == 8
    assert payload["reporting"] == {
        "model_calls": 8,
        "repair_attempts": 0,
        "raw_prompts_retained": False,
        "raw_responses_retained": False,
    }
    assert all(row["score"] == 100 for row in payload["results"])
    assert all(row["chat_output_contract_passed"] for row in payload["results"])
    assert all(
        task.prompt not in rendered and task.reference_response not in rendered
        for task in ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_TASKS
    )


def test_adversarial_local_output_script_is_zero_call_and_bounded() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/benchmark_local_output_contract.py",
            "--profile",
            "adversarial",
            "--samples",
            "3",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    rendered = json.dumps(payload)

    assert payload["profile"] == ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_PROFILE
    assert payload["task_count"] == 8
    assert payload["planned_initial_calls"] == 24
    assert payload["planned_max_calls"] == 48
    assert payload["reporting"]["model_calls"] == 0
    assert all(
        task.prompt not in rendered and task.reference_response not in rendered
        for task in ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_TASKS
    )


def test_adversarial_local_output_script_enforces_48_call_cap() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/benchmark_local_output_contract.py",
            "--profile",
            "adversarial",
            "--live",
            "--samples",
            "3",
            "--max-calls",
            "47",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "maximum calls (48) exceed --max-calls (47)" in completed.stderr


def test_local_output_contract_benchmark_refuses_empty_task_set() -> None:
    async def invoke(
        _prompt: str,
        _route_mode: str,
        _generation_policy: object,
    ) -> dict[str, object]:
        raise AssertionError("must not call adapter")

    with pytest.raises(ValueError, match="at least one benchmark task"):
        asyncio.run(
            run_local_output_contract_benchmark(
                invoke=invoke,
                tasks=(),
            )
        )


def test_local_output_contract_script_enforces_worst_case_call_cap() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/benchmark_local_output_contract.py",
            "--live",
            "--max-calls",
            "23",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "maximum calls (24) exceed --max-calls (23)" in completed.stderr


def test_local_output_contract_benchmark_sanitizes_adapter_exception() -> None:
    task = DEFAULT_CHAT_MODEL_BENCHMARK_TASKS[0]

    async def invoke(
        _prompt: str,
        _route_mode: str,
        _generation_policy: object,
    ) -> dict[str, object]:
        raise RuntimeError("provider secret detail")

    payload = asyncio.run(
        run_local_output_contract_benchmark(invoke=invoke, tasks=(task,), samples=1)
    )
    rendered = json.dumps(payload)

    assert payload["status"] == "failed"
    assert payload["reporting"]["model_calls"] == 1
    assert payload["results"][0]["error_code"] == "model_call_failed"
    assert "provider secret detail" not in rendered


def test_local_output_contract_benchmark_fails_on_output_hash_variance() -> None:
    task = next(
        task
        for task in DEFAULT_CHAT_MODEL_BENCHMARK_TASKS
        if task.task_id == "grounded_evidence_only"
    )
    calls = 0

    async def invoke(
        _prompt: str,
        route_mode: str,
        _generation_policy: object,
    ) -> dict[str, object]:
        nonlocal calls
        calls += 1
        response = task.reference_response
        if calls == 2:
            response = response.replace("Project Atlas is", "Atlas remains")
        return {
            "result": response,
            "mode": route_mode,
            "chat_model_id": "llama3.1:8b",
            "chat_deterministic_decoding_applied": True,
            "chat_structured_output_applied": False,
        }

    payload = asyncio.run(
        run_local_output_contract_benchmark(
            invoke=invoke,
            tasks=(task,),
            samples=2,
        )
    )

    assert payload["failed"] == 0
    assert payload["status"] == "failed"
    assert payload["stability"]["gate_passed"] is False
    assert payload["stability"]["tasks"][0]["quality_stable"] is True
    assert payload["stability"]["tasks"][0]["output_stable"] is False
