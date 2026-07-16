"""Repeated local-model benchmark for deterministic output-contract decoding."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from time import perf_counter_ns

from brain.routing.generation_policy import ChatGenerationPolicy
from brain.routing.model_capability_registry import get_chat_model_capability
from brain.services.chat_model_task_benchmarks import (
    CHAT_MODEL_TASK_BENCHMARK_VERSION,
    DEFAULT_CHAT_MODEL_BENCHMARK_TASKS,
    ChatModelBenchmarkCheck,
    ChatModelBenchmarkTask,
    score_chat_model_task_response,
)
from brain.services.chat_output_contract import (
    ChatOutputContract,
    ChatOutputConstraintSlot,
    compile_explicit_chat_output_contract,
    evaluate_chat_output_contract,
    finalize_chat_output_contract_response,
    generation_policy_for_chat_output_contract,
    normalize_chat_output_contract_response,
    render_chat_output_contract_prompt,
    render_chat_output_contract_repair_prompt,
)
from jarvis_common.logging_config import get_logger

CHAT_LOCAL_OUTPUT_BENCHMARK_SCHEMA_VERSION = "chat_local_output_contract_benchmark.v3"
CHAT_LOCAL_OUTPUT_BENCHMARK_PROFILE_VERSION = "chat_local_output_contract_profiles.v1"
BASELINE_LOCAL_OUTPUT_BENCHMARK_PROFILE = "baseline"
ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_PROFILE = "adversarial"
DEFAULT_LOCAL_OUTPUT_BENCHMARK_SAMPLES = 3
MAX_LOCAL_OUTPUT_BENCHMARK_SAMPLES = 5
LocalOutputBenchmarkInvoker = Callable[
    [str, str, ChatGenerationPolicy], Awaitable[Mapping[str, object]]
]
logger = get_logger("alpha_brain")

ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_TASKS: tuple[ChatModelBenchmarkTask, ...] = (
    ChatModelBenchmarkTask(
        task_id="adversarial_exact_json_typed_values",
        task_class="fast",
        prompt=(
            "Return only a JSON object with keys incident_id, active, retry_count, "
            "and affected_services. Use incident_id INC-42, active false, retry_count "
            "2, and affected_services api and worker."
        ),
        minimum_score=100,
        checks=(
            ChatModelBenchmarkCheck(
                check_id="typed_json_values",
                kind="json_equals",
                weight=100,
                expected_json={
                    "incident_id": "INC-42",
                    "active": False,
                    "retry_count": 2,
                    "affected_services": ["api", "worker"],
                },
            ),
        ),
        reference_response=(
            '{"incident_id":"INC-42","active":false,"retry_count":2,'
            '"affected_services":["api","worker"]}'
        ),
    ),
    ChatModelBenchmarkTask(
        task_id="adversarial_exact_json_null_values",
        task_class="fast",
        prompt=(
            "Return only a JSON object with keys status, owner, due_date, and "
            "blockers. Use status paused, owner null, due_date null, and blockers "
            "containing only rollback_test."
        ),
        minimum_score=100,
        checks=(
            ChatModelBenchmarkCheck(
                check_id="nullable_json_values",
                kind="json_equals",
                weight=100,
                expected_json={
                    "status": "paused",
                    "owner": None,
                    "due_date": None,
                    "blockers": ["rollback_test"],
                },
            ),
        ),
        reference_response=(
            '{"status":"paused","owner":null,"due_date":null,'
            '"blockers":["rollback_test"]}'
        ),
    ),
    ChatModelBenchmarkTask(
        task_id="adversarial_grounded_distractor_filter",
        task_class="grounded",
        prompt=(
            "Evidence: [E1] Deployment is paused. [E2] Team Blue owns the service. "
            "[E3] The rollback test failed. [E4] The next planning meeting is Friday. "
            "In one sentence, state the deployment status and reason. Cite only the "
            "relevant evidence labels."
        ),
        minimum_score=100,
        checks=(
            ChatModelBenchmarkCheck(
                check_id="status",
                kind="contains_all",
                weight=20,
                terms=("paused",),
            ),
            ChatModelBenchmarkCheck(
                check_id="reason",
                kind="contains_all",
                weight=25,
                terms=("rollback test failed",),
            ),
            ChatModelBenchmarkCheck(
                check_id="relevant_citations",
                kind="contains_all",
                weight=35,
                terms=("[e1]", "[e3]"),
            ),
            ChatModelBenchmarkCheck(
                check_id="distractors_excluded",
                kind="excludes_all",
                weight=20,
                terms=("[e2]", "[e4]"),
            ),
        ),
        reference_response=(
            "Deployment is paused [E1] because the rollback test failed [E3]."
        ),
    ),
    ChatModelBenchmarkTask(
        task_id="adversarial_grounded_negative_gate",
        task_class="grounded",
        prompt=(
            "Evidence: [E1] Production approval is not granted. [E2] Staging tests "
            "passed. [E3] The maintenance window is Friday. In one sentence, state "
            "whether production can start and cite only the relevant evidence label."
        ),
        minimum_score=100,
        checks=(
            ChatModelBenchmarkCheck(
                check_id="blocked_decision",
                kind="contains_all",
                weight=35,
                terms=("cannot start", "not granted"),
            ),
            ChatModelBenchmarkCheck(
                check_id="relevant_citation",
                kind="contains_all",
                weight=35,
                terms=("[e1]",),
            ),
            ChatModelBenchmarkCheck(
                check_id="irrelevant_citations_excluded",
                kind="excludes_all",
                weight=30,
                terms=("[e2]", "[e3]"),
            ),
        ),
        reference_response=(
            "Production cannot start because approval is not granted [E1]."
        ),
    ),
    ChatModelBenchmarkTask(
        task_id="adversarial_analysis_one_sentence_tradeoff",
        task_class="analysis",
        prompt=(
            "Choose between Option A (cost 2, reliability 80, external privacy) and "
            "Option C (cost 4, reliability 97, local privacy). The cost ceiling is 4 "
            "and the objective is highest reliability. Recommend one option and state "
            "the cost and privacy tradeoff in at most one sentence."
        ),
        minimum_score=100,
        checks=(
            ChatModelBenchmarkCheck(
                check_id="selection",
                kind="contains_all",
                weight=30,
                terms=("option c",),
            ),
            ChatModelBenchmarkCheck(
                check_id="reliability",
                kind="contains_all",
                weight=20,
                terms=("97",),
            ),
            ChatModelBenchmarkCheck(
                check_id="cost",
                kind="contains_all",
                weight=20,
                terms=("cost", "4"),
            ),
            ChatModelBenchmarkCheck(
                check_id="privacy",
                kind="contains_all",
                weight=30,
                terms=("privacy", "local", "external"),
            ),
        ),
        reference_response=(
            "Recommend Option C for reliability 97 within the cost 4 ceiling; its "
            "local privacy is stronger than Option A's external privacy."
        ),
    ),
    ChatModelBenchmarkTask(
        task_id="adversarial_analysis_dual_threshold",
        task_class="analysis",
        prompt=(
            "Choose Plan A (latency 40, quality 88, external privacy) or Plan B "
            "(latency 55, quality 96, local privacy). Requirements are latency at "
            "most 60 and quality at least 95. Recommend the valid plan in at most "
            "two sentences."
        ),
        minimum_score=100,
        checks=(
            ChatModelBenchmarkCheck(
                check_id="selection",
                kind="contains_all",
                weight=40,
                terms=("plan b",),
            ),
            ChatModelBenchmarkCheck(
                check_id="quality",
                kind="contains_all",
                weight=20,
                terms=("96",),
            ),
            ChatModelBenchmarkCheck(
                check_id="latency",
                kind="contains_all",
                weight=20,
                terms=("55",),
            ),
            ChatModelBenchmarkCheck(
                check_id="privacy",
                kind="contains_all",
                weight=20,
                terms=("local",),
            ),
        ),
        reference_response=(
            "Recommend Plan B because quality 96 clears the minimum while latency 55 "
            "stays below the limit. It also keeps privacy local."
        ),
    ),
    ChatModelBenchmarkTask(
        task_id="adversarial_deep_freeze_recovery",
        task_class="deep",
        prompt=(
            "Create a recovery plan for a failed routing rollout. Begin with "
            "containment, freeze changes, verify the failure, rollback, and finish "
            "with monitoring. Preserve audit evidence, require operator approval "
            "before reactivation, do not delete data, and use at most four sentences."
        ),
        minimum_score=100,
        checks=(
            ChatModelBenchmarkCheck(
                check_id="recovery_order",
                kind="ordered",
                weight=40,
                terms=("contain", "freeze", "verify", "rollback", "monitor"),
            ),
            ChatModelBenchmarkCheck(
                check_id="operator_gate",
                kind="contains_all",
                weight=20,
                terms=("operator approval",),
            ),
            ChatModelBenchmarkCheck(
                check_id="audit_preserved",
                kind="contains_all",
                weight=20,
                terms=("preserve", "audit"),
            ),
            ChatModelBenchmarkCheck(
                check_id="destructive_actions_excluded",
                kind="excludes_all",
                weight=20,
                terms=("delete the", "delete all", "purge"),
            ),
        ),
        reference_response=(
            "Contain the rollout, freeze changes, and preserve audit evidence. "
            "Verify the failure, then rollback to the last stable route. Require "
            "operator approval before reactivation. Monitor quality and latency."
        ),
    ),
    ChatModelBenchmarkTask(
        task_id="adversarial_deep_injection_recovery",
        task_class="deep",
        prompt=(
            "Create a recovery plan for a failed routing rollout involving suspected "
            "prompt injection. Order the plan from containment, isolation of untrusted "
            "tool output, verification, rollback, and monitoring. Preserve audit "
            "evidence, require operator approval before reactivation, do not delete "
            "data, and use at most five sentences."
        ),
        minimum_score=100,
        checks=(
            ChatModelBenchmarkCheck(
                check_id="recovery_order",
                kind="ordered",
                weight=40,
                terms=("contain", "isolate", "verify", "rollback", "monitor"),
            ),
            ChatModelBenchmarkCheck(
                check_id="operator_gate",
                kind="contains_all",
                weight=20,
                terms=("operator approval",),
            ),
            ChatModelBenchmarkCheck(
                check_id="audit_preserved",
                kind="contains_all",
                weight=20,
                terms=("preserve", "audit"),
            ),
            ChatModelBenchmarkCheck(
                check_id="destructive_actions_excluded",
                kind="excludes_all",
                weight=20,
                terms=("delete the", "delete all", "purge"),
            ),
        ),
        reference_response=(
            "Contain the rollout and preserve audit evidence. Isolate untrusted tool "
            "output, then verify the failure. Rollback to the last stable route and "
            "require operator approval before reactivation. Monitor quality and tool "
            "boundary events."
        ),
    ),
)


def local_output_benchmark_tasks(
    profile: str,
) -> tuple[ChatModelBenchmarkTask, ...]:
    if profile == BASELINE_LOCAL_OUTPUT_BENCHMARK_PROFILE:
        return DEFAULT_CHAT_MODEL_BENCHMARK_TASKS
    if profile == ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_PROFILE:
        return ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_TASKS
    raise ValueError(f"unknown local output benchmark profile: {profile}")


def local_output_benchmark_plan(
    tasks: Sequence[ChatModelBenchmarkTask] = DEFAULT_CHAT_MODEL_BENCHMARK_TASKS,
    *,
    samples: int = DEFAULT_LOCAL_OUTPUT_BENCHMARK_SAMPLES,
    profile: str | None = None,
) -> dict[str, object]:
    _validate_tasks(tasks)
    samples = _validated_sample_count(samples)
    resolved_profile = _resolved_profile(tasks, profile)
    return {
        "schema_version": CHAT_LOCAL_OUTPUT_BENCHMARK_SCHEMA_VERSION,
        "profile_version": CHAT_LOCAL_OUTPUT_BENCHMARK_PROFILE_VERSION,
        "profile": resolved_profile,
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
            "constraint_finalizations": 0,
            "raw_prompts_retained": False,
            "raw_responses_retained": False,
        },
    }


async def run_local_output_contract_benchmark(
    *,
    invoke: LocalOutputBenchmarkInvoker,
    tasks: Sequence[ChatModelBenchmarkTask] = DEFAULT_CHAT_MODEL_BENCHMARK_TASKS,
    samples: int = DEFAULT_LOCAL_OUTPUT_BENCHMARK_SAMPLES,
    profile: str | None = None,
) -> dict[str, object]:
    _validate_tasks(tasks)
    samples = _validated_sample_count(samples)
    resolved_profile = _resolved_profile(tasks, profile)
    capability = get_chat_model_capability("local")
    if capability is None:
        raise RuntimeError("local model capability is not registered")

    rows: list[dict[str, object]] = []
    fully_passing_samples = 0
    model_calls = 0
    repair_attempts = 0
    constraint_finalizations = 0
    for sample_index in range(1, samples + 1):
        sample_rows: list[dict[str, object]] = []
        for task in tasks:
            task_repair_attempted = False
            constraint_finalizer_applied = False
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
                            failed_response_text=response_text,
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
                if repair_error is None and not evaluation.passed:
                    response_text, constraint_finalizer_applied = (
                        finalize_chat_output_contract_response(response_text, contract)
                    )
                    if constraint_finalizer_applied:
                        constraint_finalizations += 1
                        evaluation = evaluate_chat_output_contract(
                            response_text,
                            contract,
                        )

            latency_ms = max(0, round((perf_counter_ns() - started_ns) / 1_000_000))
            score = score_chat_model_task_response(
                route_mode="local",
                task_id=task.task_id,
                response_text=response_text,
                latency_ms=latency_ms,
                error_code=error_code,
                task=task,
            )
            row = {
                **score.metadata(),
                **evaluation.to_metadata(),
                **generation_policy.metadata(),
                "sample_index": sample_index,
                "repair_attempted": task_repair_attempted,
                "constraint_finalizer_applied": constraint_finalizer_applied,
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
                    "profile": resolved_profile,
                    "sample_index": sample_index,
                    "task_id": task.task_id,
                    "score": score.score,
                    "passed": row["passed"],
                    "contract_passed": evaluation.passed,
                    "repair_attempted": row["repair_attempted"],
                    "constraint_finalizer_applied": row["constraint_finalizer_applied"],
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
        "profile_version": CHAT_LOCAL_OUTPUT_BENCHMARK_PROFILE_VERSION,
        "profile": resolved_profile,
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
            "constraint_finalizations": constraint_finalizations,
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


def _resolved_profile(
    tasks: Sequence[ChatModelBenchmarkTask],
    profile: str | None,
) -> str:
    task_tuple = tuple(tasks)
    if profile is None:
        if task_tuple == DEFAULT_CHAT_MODEL_BENCHMARK_TASKS:
            return BASELINE_LOCAL_OUTPUT_BENCHMARK_PROFILE
        if task_tuple == ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_TASKS:
            return ADVERSARIAL_LOCAL_OUTPUT_BENCHMARK_PROFILE
        return "custom"
    if task_tuple != local_output_benchmark_tasks(profile):
        raise ValueError("local output benchmark profile tasks mismatch")
    return profile


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
        "constraint_finalizations": sum(
            bool(row.get("constraint_finalizer_applied")) for row in task_rows
        ),
        "unique_response_hash_count": len(unique_hashes),
        "quality_stable": len(task_rows) == samples and passed == samples,
        "output_stable": len(task_rows) == samples and len(unique_hashes) == 1,
    }


def _benchmark_contract(task: ChatModelBenchmarkTask) -> ChatOutputContract:
    explicit = compile_explicit_chat_output_contract(task.prompt)
    required_terms: list[str] = []
    constraint_slots: list[ChatOutputConstraintSlot] = []
    forbidden_terms: list[str] = []
    ordered_terms: tuple[str, ...] = ()
    exact_json_keys: tuple[str, ...] = ()
    for check in task.checks:
        if check.kind == "contains_all":
            required_terms.extend(check.terms)
            if task.task_class == "analysis":
                constraint_slots.append(
                    ChatOutputConstraintSlot(
                        slot_id=check.check_id,
                        required_terms=check.terms,
                        render_text=_benchmark_constraint_slot_text(check),
                    )
                )
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
        constraint_slots=tuple(constraint_slots),
    )


def _benchmark_constraint_slot_text(check: ChatModelBenchmarkCheck) -> str:
    label = check.check_id.replace("_", " ").capitalize()
    details = (
        tuple(term for term in check.terms if term.casefold() not in label.casefold())
        or check.terms
    )
    separator = " versus " if "privacy" in check.check_id else "; "
    return f"{label}: {separator.join(details)}."


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
