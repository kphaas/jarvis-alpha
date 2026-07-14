"""Advisory local-model benchmark for the Phase 29 output-contract pipeline."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import perf_counter_ns

from brain.routing.model_capability_registry import get_chat_model_capability
from brain.services.chat_model_task_benchmarks import (
    CHAT_MODEL_TASK_BENCHMARK_VERSION,
    DEFAULT_CHAT_MODEL_BENCHMARK_TASKS,
    BenchmarkInvoker,
    ChatModelBenchmarkTask,
    score_chat_model_task_response,
)
from brain.services.chat_output_contract import (
    ChatOutputContract,
    compile_explicit_chat_output_contract,
    evaluate_chat_output_contract,
    normalize_chat_output_contract_response,
    render_chat_output_contract_prompt,
    render_chat_output_contract_repair_prompt,
)
from jarvis_common.logging_config import get_logger

CHAT_LOCAL_OUTPUT_BENCHMARK_SCHEMA_VERSION = "chat_local_output_contract_benchmark.v1"
logger = get_logger("alpha_brain")


def local_output_benchmark_plan(
    tasks: Sequence[ChatModelBenchmarkTask] = DEFAULT_CHAT_MODEL_BENCHMARK_TASKS,
) -> dict[str, object]:
    return {
        "schema_version": CHAT_LOCAL_OUTPUT_BENCHMARK_SCHEMA_VERSION,
        "benchmark_version": CHAT_MODEL_TASK_BENCHMARK_VERSION,
        "status": "planned",
        "advisory_only": True,
        "local_only": True,
        "routing_scores_mutated": False,
        "task_count": len(tasks),
        "planned_initial_calls": len(tasks),
        "planned_max_calls": len(tasks) * 2,
        "reporting": {
            "model_calls": 0,
            "repair_attempts": 0,
            "raw_prompts_retained": False,
            "raw_responses_retained": False,
        },
    }


async def run_local_output_contract_benchmark(
    *,
    invoke: BenchmarkInvoker,
    tasks: Sequence[ChatModelBenchmarkTask] = DEFAULT_CHAT_MODEL_BENCHMARK_TASKS,
) -> dict[str, object]:
    capability = get_chat_model_capability("local")
    if capability is None:
        raise RuntimeError("local model capability is not registered")

    rows: list[dict[str, object]] = []
    model_calls = 0
    repair_attempts = 0
    for task in tasks:
        task_repair_attempted = False
        contract = _benchmark_contract(task)
        started_ns = perf_counter_ns()
        try:
            response = await invoke(
                render_chat_output_contract_prompt(
                    prompt=task.prompt,
                    contract=contract,
                ),
                "local",
            )
        except Exception:
            response = {"mode": "local", "error": True}
        model_calls += 1
        response_text = str(response.get("result") or "")
        error_code = _response_error(response, capability.model_id)
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
                )
            except Exception:
                repair = {"mode": "local", "error": True}
            model_calls += 1
            repair_error = _response_error(repair, capability.model_id)
            if repair_error is None:
                response_text = str(repair.get("result") or "")
                error_code = None
            else:
                error_code = repair_error
            response_text, retry_normalized = normalize_chat_output_contract_response(
                response_text,
                contract,
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
            "repair_attempted": task_repair_attempted,
            "deterministic_normalization_applied": normalized,
        }
        row["passed"] = score.passed and evaluation.passed
        rows.append(row)
        logger.info(
            "CHAT_LOCAL_OUTPUT_CONTRACT_BENCHMARK_COMPLETED",
            extra={
                "event": "CHAT_LOCAL_OUTPUT_CONTRACT_BENCHMARK_COMPLETED",
                "task_id": task.task_id,
                "score": score.score,
                "passed": row["passed"],
                "contract_passed": evaluation.passed,
                "repair_attempted": row["repair_attempted"],
                "latency_ms": latency_ms,
                "error_code": score.error_code,
            },
        )

    failed = sum(not bool(row["passed"]) for row in rows)
    return {
        "schema_version": CHAT_LOCAL_OUTPUT_BENCHMARK_SCHEMA_VERSION,
        "benchmark_version": CHAT_MODEL_TASK_BENCHMARK_VERSION,
        "status": "failed" if failed else "passed",
        "advisory_only": True,
        "local_only": True,
        "routing_scores_mutated": False,
        "passed": len(rows) - failed,
        "failed": failed,
        "results": rows,
        "reporting": {
            "model_calls": model_calls,
            "repair_attempts": repair_attempts,
            "raw_prompts_retained": False,
            "raw_responses_retained": False,
        },
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


def _response_error(response: Mapping[str, object], model_id: str) -> str | None:
    if response.get("error"):
        return "model_call_failed"
    if response.get("mode") != "local":
        return "route_mismatch"
    if response.get("chat_model_id") != model_id:
        return "model_identity_mismatch"
    return None
