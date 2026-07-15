"""Repeated local-model benchmark for deterministic output-contract decoding."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from time import perf_counter_ns

from brain.routing.generation_policy import ChatGenerationPolicy
from brain.routing.model_capability_registry import get_chat_model_capability
from brain.services.chat_model_task_benchmarks import (
    CHAT_MODEL_TASK_BENCHMARK_VERSION,
    DEFAULT_CHAT_MODEL_BENCHMARK_TASKS,
    ChatModelBenchmarkTask,
    score_chat_model_task_response,
)
from brain.services.chat_output_contract import (
    ChatOutputContract,
    compile_explicit_chat_output_contract,
    evaluate_chat_output_contract,
    generation_policy_for_chat_output_contract,
    normalize_chat_output_contract_response,
    render_chat_output_contract_prompt,
    render_chat_output_contract_repair_prompt,
)
from jarvis_common.logging_config import get_logger

CHAT_LOCAL_OUTPUT_BENCHMARK_SCHEMA_VERSION = "chat_local_output_contract_benchmark.v2"
DEFAULT_LOCAL_OUTPUT_BENCHMARK_SAMPLES = 3
MAX_LOCAL_OUTPUT_BENCHMARK_SAMPLES = 5
LocalOutputBenchmarkInvoker = Callable[
    [str, str, ChatGenerationPolicy], Awaitable[Mapping[str, object]]
]
logger = get_logger("alpha_brain")


def local_output_benchmark_plan(
    tasks: Sequence[ChatModelBenchmarkTask] = DEFAULT_CHAT_MODEL_BENCHMARK_TASKS,
    *,
    samples: int = DEFAULT_LOCAL_OUTPUT_BENCHMARK_SAMPLES,
) -> dict[str, object]:
    _validate_tasks(tasks)
    samples = _validated_sample_count(samples)
    return {
        "schema_version": CHAT_LOCAL_OUTPUT_BENCHMARK_SCHEMA_VERSION,
        "benchmark_version": CHAT_MODEL_TASK_BENCHMARK_VERSION,
        "status": "planned",
        "advisory_only": True,
        "local_only": True,
        "routing_scores_mutated": False,
        "task_count": len(tasks),
        "samples": samples,
        "planned_initial_calls": len(tasks) * samples,
        "planned_max_calls": len(tasks) * samples * 2,
        "stability_gate_requires_all_samples": True,
        "reporting": {
            "model_calls": 0,
            "repair_attempts": 0,
            "raw_prompts_retained": False,
            "raw_responses_retained": False,
        },
    }


async def run_local_output_contract_benchmark(
    *,
    invoke: LocalOutputBenchmarkInvoker,
    tasks: Sequence[ChatModelBenchmarkTask] = DEFAULT_CHAT_MODEL_BENCHMARK_TASKS,
    samples: int = DEFAULT_LOCAL_OUTPUT_BENCHMARK_SAMPLES,
) -> dict[str, object]:
    _validate_tasks(tasks)
    samples = _validated_sample_count(samples)
    capability = get_chat_model_capability("local")
    if capability is None:
        raise RuntimeError("local model capability is not registered")

    rows: list[dict[str, object]] = []
    fully_passing_samples = 0
    model_calls = 0
    repair_attempts = 0
    for sample_index in range(1, samples + 1):
        sample_rows: list[dict[str, object]] = []
        for task in tasks:
            task_repair_attempted = False
            contract = _benchmark_contract(task)
            generation_policy = generation_policy_for_chat_output_contract(contract)
            started_ns = perf_counter_ns()
            try:
                response = await invoke(
                    render_chat_output_contract_prompt(
                        prompt=task.prompt,
                        contract=contract,
                    ),
                    "local",
                    generation_policy,
                )
            except Exception:
                response = {"mode": "local", "error": True}
            model_calls += 1
            final_response = response
            response_text = str(response.get("result") or "")
            error_code = _response_error(
                response,
                capability.model_id,
                generation_policy,
            )
            response_text, normalized = normalize_chat_output_contract_response(
                response_text,
                contract,
            )
            evaluation = evaluate_chat_output_contract(response_text, contract)

            if error_code is None and not evaluation.passed:
                task_repair_attempted = True
                repair_attempts += 1
                try:
                    repair = await invoke(
                        render_chat_output_contract_repair_prompt(
                            user_msg=task.prompt,
                            contract=contract,
                            issues=evaluation.issues,
                        ),
                        "local",
                        generation_policy,
                    )
                except Exception:
                    repair = {"mode": "local", "error": True}
                model_calls += 1
                final_response = repair
                repair_error = _response_error(
                    repair,
                    capability.model_id,
                    generation_policy,
                )
                if repair_error is None:
                    response_text = str(repair.get("result") or "")
                    error_code = None
                else:
                    error_code = repair_error
                response_text, retry_normalized = (
                    normalize_chat_output_contract_response(response_text, contract)
                )
                normalized = normalized or retry_normalized
                evaluation = evaluate_chat_output_contract(response_text, contract)

            latency_ms = max(0, round((perf_counter_ns() - started_ns) / 1_000_000))
            score = score_chat_model_task_response(
                route_mode="local",
                task_id=task.task_id,
                response_text=response_text,
                latency_ms=latency_ms,
                error_code=error_code,
            )
            row = {
                **score.metadata(),
                **evaluation.to_metadata(),
                **generation_policy.metadata(),
                "sample_index": sample_index,
                "repair_attempted": task_repair_attempted,
                "deterministic_normalization_applied": normalized,
                "chat_deterministic_decoding_applied": final_response.get(
                    "chat_deterministic_decoding_applied"
                )
                is True,
                "chat_structured_output_applied": final_response.get(
                    "chat_structured_output_applied"
                )
                is True,
                "chat_exact_key_schema_applied": final_response.get(
                    "chat_exact_key_schema_applied"
                )
                is True,
            }
            row["passed"] = score.passed and evaluation.passed
            rows.append(row)
            sample_rows.append(row)
            logger.info(
                "CHAT_LOCAL_OUTPUT_CONTRACT_BENCHMARK_COMPLETED",
                extra={
                    "event": "CHAT_LOCAL_OUTPUT_CONTRACT_BENCHMARK_COMPLETED",
                    "sample_index": sample_index,
                    "task_id": task.task_id,
                    "score": score.score,
                    "passed": row["passed"],
                    "contract_passed": evaluation.passed,
                    "repair_attempted": row["repair_attempted"],
                    "latency_ms": latency_ms,
                    "error_code": score.error_code,
                },
            )
        fully_passing_samples += int(all(bool(row["passed"]) for row in sample_rows))

    failed = sum(not bool(row["passed"]) for row in rows)
    task_stability = [_task_stability(task.task_id, rows, samples) for task in tasks]
    stability_gate_passed = all(
        bool(task["quality_stable"]) and bool(task["output_stable"])
        for task in task_stability
    )
    return {
        "schema_version": CHAT_LOCAL_OUTPUT_BENCHMARK_SCHEMA_VERSION,
        "benchmark_version": CHAT_MODEL_TASK_BENCHMARK_VERSION,
        "status": "passed" if stability_gate_passed else "failed",
        "advisory_only": True,
        "local_only": True,
        "routing_scores_mutated": False,
        "passed": len(rows) - failed,
        "failed": failed,
        "results": rows,
        "stability": {
            "required_samples": samples,
            "fully_passing_samples": fully_passing_samples,
            "task_attempts_passed": len(rows) - failed,
            "task_attempts_total": len(rows),
            "stable_tasks": sum(
                bool(task["quality_stable"]) and bool(task["output_stable"])
                for task in task_stability
            ),
            "task_count": len(task_stability),
            "gate_passed": stability_gate_passed,
            "tasks": task_stability,
        },
        "reporting": {
            "model_calls": model_calls,
            "repair_attempts": repair_attempts,
            "raw_prompts_retained": False,
            "raw_responses_retained": False,
        },
    }


def _validated_sample_count(samples: int) -> int:
    if samples < 1 or samples > MAX_LOCAL_OUTPUT_BENCHMARK_SAMPLES:
        raise ValueError(
            f"samples must be between 1 and {MAX_LOCAL_OUTPUT_BENCHMARK_SAMPLES}"
        )
    return samples


def _validate_tasks(tasks: Sequence[ChatModelBenchmarkTask]) -> None:
    task_ids = [task.task_id for task in tasks]
    if not task_ids:
        raise ValueError("at least one benchmark task is required")
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("benchmark task IDs must be unique")


def _task_stability(
    task_id: str,
    rows: Sequence[Mapping[str, object]],
    samples: int,
) -> dict[str, object]:
    task_rows = [row for row in rows if row.get("task_id") == task_id]
    unique_hashes = {str(row.get("response_sha256") or "") for row in task_rows}
    passed = sum(bool(row.get("passed")) for row in task_rows)
    return {
        "task_id": task_id,
        "attempts": len(task_rows),
        "passed": passed,
        "repair_attempts": sum(bool(row.get("repair_attempted")) for row in task_rows),
        "unique_response_hash_count": len(unique_hashes),
        "quality_stable": len(task_rows) == samples and passed == samples,
        "output_stable": len(task_rows) == samples and len(unique_hashes) == 1,
    }


def _benchmark_contract(task: ChatModelBenchmarkTask) -> ChatOutputContract:
    explicit = compile_explicit_chat_output_contract(task.prompt)
    required_terms: list[str] = []
    forbidden_terms: list[str] = []
    ordered_terms: tuple[str, ...] = ()
    exact_json_keys: tuple[str, ...] = ()
    for check in task.checks:
        if check.kind == "contains_all":
            required_terms.extend(check.terms)
        elif check.kind == "excludes_all":
            forbidden_terms.extend(check.terms)
        elif check.kind == "ordered":
            ordered_terms = check.terms
        elif check.kind == "json_equals" and check.expected_json is not None:
            exact_json_keys = tuple(str(key) for key in check.expected_json)
    return ChatOutputContract(
        contract_id=f"benchmark:{task.task_id}",
        exact_json_keys=exact_json_keys
        or (explicit.exact_json_keys if explicit is not None else ()),
        required_terms=tuple(dict.fromkeys(required_terms)),
        forbidden_terms=tuple(dict.fromkeys(forbidden_terms)),
        ordered_terms=ordered_terms,
        max_sentences=explicit.max_sentences if explicit is not None else None,
    )


def _response_error(
    response: Mapping[str, object],
    model_id: str,
    generation_policy: ChatGenerationPolicy,
) -> str | None:
    if response.get("error"):
        return "model_call_failed"
    if response.get("mode") != "local":
        return "route_mismatch"
    if response.get("chat_model_id") != model_id:
        return "model_identity_mismatch"
    if generation_policy.deterministic and not response.get(
        "chat_deterministic_decoding_applied"
    ):
        return "decoding_policy_not_applied"
    if generation_policy.json_mode and not response.get(
        "chat_structured_output_applied"
    ):
        return "structured_output_not_applied"
    if generation_policy.exact_json_keys and not response.get(
        "chat_exact_key_schema_applied"
    ):
        return "exact_key_schema_not_applied"
    return None
