"""Versioned, advisory-only task benchmarks for registered chat models."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from time import perf_counter_ns
from typing import Literal

from brain.routing.model_capability_registry import (
    CHAT_MODEL_CAPABILITY_REGISTRY_VERSION,
    DEFAULT_CHAT_MODEL_CAPABILITIES,
    ChatModelCapability,
    ChatTaskClass,
    get_chat_model_capability,
)
from jarvis_common.logging_config import get_logger

CHAT_MODEL_TASK_BENCHMARK_VERSION = "chat_model_task_benchmark.v1"
CHAT_MODEL_TASK_BENCHMARK_SCHEMA_VERSION = "chat_model_task_benchmark_result.v1"

BenchmarkCheckKind = Literal["contains_all", "excludes_all", "ordered", "json_equals"]
BenchmarkInvoker = Callable[[str, str], Awaitable[Mapping[str, object]]]
TimerNs = Callable[[], int]

logger = get_logger("alpha_brain")
_ALLOWED_ERROR_CODES = frozenset(
    {
        "model_call_failed",
        "model_adapter_exception",
        "model_identity_mismatch",
        "route_mismatch",
        "decoding_policy_not_applied",
        "structured_output_not_applied",
    }
)


@dataclass(frozen=True)
class ChatModelBenchmarkCheck:
    check_id: str
    kind: BenchmarkCheckKind
    weight: int
    terms: tuple[str, ...] = ()
    expected_json: Mapping[str, object] | None = None


@dataclass(frozen=True)
class ChatModelBenchmarkTask:
    task_id: str
    task_class: ChatTaskClass
    prompt: str
    minimum_score: int
    checks: tuple[ChatModelBenchmarkCheck, ...]
    reference_response: str


@dataclass(frozen=True)
class ChatModelTaskBenchmarkResult:
    task_id: str
    task_class: ChatTaskClass
    route_mode: str
    provider: str
    model_id: str
    deployment: str
    privacy_tier: str
    cost_tier: int
    registry_task_score: int
    score: int
    minimum_score: int
    passed: bool
    latency_ms: int
    response_chars: int
    response_sha256: str
    checks: tuple[dict[str, object], ...]
    error_code: str | None = None

    def metadata(self) -> dict[str, object]:
        return {
            "schema_version": CHAT_MODEL_TASK_BENCHMARK_SCHEMA_VERSION,
            "benchmark_version": CHAT_MODEL_TASK_BENCHMARK_VERSION,
            "registry_version": CHAT_MODEL_CAPABILITY_REGISTRY_VERSION,
            "task_id": self.task_id,
            "task_class": self.task_class,
            "route_mode": self.route_mode,
            "provider": self.provider,
            "model_id": self.model_id,
            "deployment": self.deployment,
            "privacy_tier": self.privacy_tier,
            "cost_tier": self.cost_tier,
            "registry_task_score": self.registry_task_score,
            "score": self.score,
            "minimum_score": self.minimum_score,
            "passed": self.passed,
            "latency_ms": self.latency_ms,
            "response_chars": self.response_chars,
            "response_sha256": self.response_sha256,
            "checks": list(self.checks),
            "error_code": self.error_code,
            "raw_response_retained": False,
        }


DEFAULT_CHAT_MODEL_BENCHMARK_TASKS: tuple[ChatModelBenchmarkTask, ...] = (
    ChatModelBenchmarkTask(
        task_id="fast_exact_json",
        task_class="fast",
        prompt=(
            "Return only a JSON object with keys owner, priority, and ticket_count. "
            "Use this data: owner is Delta; priority is high; open tickets are T-14, "
            "T-18, and T-22."
        ),
        minimum_score=100,
        checks=(
            ChatModelBenchmarkCheck(
                check_id="exact_json",
                kind="json_equals",
                weight=100,
                expected_json={
                    "owner": "Delta",
                    "priority": "high",
                    "ticket_count": 3,
                },
            ),
        ),
        reference_response=('{"owner":"Delta","priority":"high","ticket_count":3}'),
    ),
    ChatModelBenchmarkTask(
        task_id="grounded_evidence_only",
        task_class="grounded",
        prompt=(
            "Evidence: [E1] Project Atlas deployment is paused. [E2] Release can "
            "resume only after the rollback test passes. [E3] The owner is Team Blue. "
            "In one sentence, state the deployment status and release condition. "
            "Cite only the relevant evidence labels."
        ),
        minimum_score=80,
        checks=(
            ChatModelBenchmarkCheck(
                check_id="status_fact",
                kind="contains_all",
                weight=25,
                terms=("paused",),
            ),
            ChatModelBenchmarkCheck(
                check_id="release_condition",
                kind="contains_all",
                weight=25,
                terms=("resume", "rollback test"),
            ),
            ChatModelBenchmarkCheck(
                check_id="relevant_citations",
                kind="contains_all",
                weight=30,
                terms=("[e1]", "[e2]"),
            ),
            ChatModelBenchmarkCheck(
                check_id="irrelevant_evidence_excluded",
                kind="excludes_all",
                weight=20,
                terms=("[e3]",),
            ),
        ),
        reference_response=(
            "Project Atlas is paused [E1] and can resume only after the rollback "
            "test passes [E2]."
        ),
    ),
    ChatModelBenchmarkTask(
        task_id="analysis_bounded_tradeoff",
        task_class="analysis",
        prompt=(
            "Choose between Option A (cost 2, reliability 70, external privacy) and "
            "Option B (cost 3, reliability 92, local privacy). The cost ceiling is 3 "
            "and the objective is highest reliability. Recommend one option and "
            "explain the cost and privacy tradeoff in at most three sentences."
        ),
        minimum_score=80,
        checks=(
            ChatModelBenchmarkCheck(
                check_id="correct_selection",
                kind="contains_all",
                weight=35,
                terms=("option b",),
            ),
            ChatModelBenchmarkCheck(
                check_id="reliability_evidence",
                kind="contains_all",
                weight=20,
                terms=("92",),
            ),
            ChatModelBenchmarkCheck(
                check_id="cost_constraint",
                kind="contains_all",
                weight=20,
                terms=("cost", "3"),
            ),
            ChatModelBenchmarkCheck(
                check_id="privacy_tradeoff",
                kind="contains_all",
                weight=25,
                terms=("privacy", "local", "external"),
            ),
        ),
        reference_response=(
            "Recommend Option B because its reliability is 92 within the cost 3 "
            "ceiling. Its local privacy is also stronger than Option A's external "
            "privacy, at one additional cost unit."
        ),
    ),
    ChatModelBenchmarkTask(
        task_id="deep_safe_recovery_plan",
        task_class="deep",
        prompt=(
            "Create a concise recovery plan for a failed routing rollout. Constraints: "
            "preserve audit evidence, require operator approval before reactivation, "
            "and do not delete data. Order the plan from containment through monitoring."
        ),
        minimum_score=80,
        checks=(
            ChatModelBenchmarkCheck(
                check_id="safe_order",
                kind="ordered",
                weight=40,
                terms=("contain", "verify", "rollback", "monitor"),
            ),
            ChatModelBenchmarkCheck(
                check_id="operator_gate",
                kind="contains_all",
                weight=20,
                terms=("operator approval",),
            ),
            ChatModelBenchmarkCheck(
                check_id="audit_preservation",
                kind="contains_all",
                weight=20,
                terms=("preserve", "audit"),
            ),
            ChatModelBenchmarkCheck(
                check_id="destructive_action_excluded",
                kind="excludes_all",
                weight=20,
                terms=("delete the", "delete all", "purge"),
            ),
        ),
        reference_response=(
            "Contain the rollout and preserve the audit evidence. Verify the failure, "
            "then rollback to static routing. Require operator approval before "
            "reactivation and monitor acceptance and latency after recovery."
        ),
    ),
)


def validate_chat_model_benchmark_tasks(
    tasks: Sequence[ChatModelBenchmarkTask] = DEFAULT_CHAT_MODEL_BENCHMARK_TASKS,
) -> tuple[str, ...]:
    failures: list[str] = []
    seen: set[str] = set()
    for task in tasks:
        if task.task_id in seen:
            failures.append(f"{task.task_id}:duplicate")
        seen.add(task.task_id)
        if not task.prompt.strip():
            failures.append(f"{task.task_id}:prompt")
        if sum(check.weight for check in task.checks) != 100:
            failures.append(f"{task.task_id}:weights")
        if not 0 <= task.minimum_score <= 100:
            failures.append(f"{task.task_id}:minimum_score")
        for check in task.checks:
            if check.weight <= 0:
                failures.append(f"{task.task_id}:{check.check_id}:weight")
            if check.kind == "json_equals" and check.expected_json is None:
                failures.append(f"{task.task_id}:{check.check_id}:expected_json")
            if check.kind != "json_equals" and not check.terms:
                failures.append(f"{task.task_id}:{check.check_id}:terms")
    return tuple(failures)


def chat_model_benchmark_plan(
    *,
    route_modes: Sequence[str],
    task_ids: Sequence[str] | None = None,
) -> dict[str, object]:
    capabilities = _selected_capabilities(route_modes)
    tasks = _selected_tasks(task_ids)
    return {
        "schema_version": CHAT_MODEL_TASK_BENCHMARK_SCHEMA_VERSION,
        "benchmark_version": CHAT_MODEL_TASK_BENCHMARK_VERSION,
        "registry_version": CHAT_MODEL_CAPABILITY_REGISTRY_VERSION,
        "status": "planned",
        "advisory_only": True,
        "routing_scores_mutated": False,
        "models": [
            {
                "route_mode": capability.route_mode,
                "provider": capability.provider,
                "model_id": capability.model_id,
                "deployment": capability.deployment,
                "privacy_tier": capability.privacy_tier,
                "cost_tier": capability.cost_tier,
            }
            for capability in capabilities
        ],
        "tasks": [
            {"task_id": task.task_id, "task_class": task.task_class} for task in tasks
        ],
        "planned_model_calls": len(capabilities) * len(tasks),
        "reporting": {
            "model_calls": 0,
            "raw_prompts_retained": False,
            "raw_responses_retained": False,
        },
    }


def score_chat_model_task_response(
    *,
    route_mode: str,
    task_id: str,
    response_text: str,
    latency_ms: int,
    error_code: str | None = None,
) -> ChatModelTaskBenchmarkResult:
    capability = get_chat_model_capability(route_mode)
    if capability is None:
        raise ValueError(f"unknown route mode: {route_mode}")
    task = _task_by_id(task_id)
    check_results = tuple(
        {
            "check_id": check.check_id,
            "passed": _check_passed(check, response_text),
            "weight": check.weight,
        }
        for check in task.checks
    )
    score = sum(
        int(check["weight"]) for check in check_results if check["passed"] is True
    )
    normalized_error = _normalized_error_code(error_code)
    return ChatModelTaskBenchmarkResult(
        task_id=task.task_id,
        task_class=task.task_class,
        route_mode=capability.route_mode,
        provider=capability.provider,
        model_id=capability.model_id,
        deployment=capability.deployment,
        privacy_tier=capability.privacy_tier,
        cost_tier=capability.cost_tier,
        registry_task_score=capability.task_scores[task.task_class],
        score=score,
        minimum_score=task.minimum_score,
        passed=normalized_error is None and score >= task.minimum_score,
        latency_ms=max(0, latency_ms),
        response_chars=len(response_text),
        response_sha256=hashlib.sha256(response_text.encode()).hexdigest(),
        checks=check_results,
        error_code=normalized_error,
    )


async def run_chat_model_task_benchmarks(
    *,
    route_modes: Sequence[str],
    invoke: BenchmarkInvoker,
    task_ids: Sequence[str] | None = None,
    timer_ns: TimerNs = perf_counter_ns,
) -> dict[str, object]:
    capabilities = _selected_capabilities(route_modes)
    tasks = _selected_tasks(task_ids)
    results: list[ChatModelTaskBenchmarkResult] = []
    for capability in capabilities:
        for task in tasks:
            started_ns = timer_ns()
            response_text = ""
            error_code: str | None = None
            try:
                response = await invoke(task.prompt, capability.route_mode)
                response_text = str(response.get("result") or "")
                if response.get("error"):
                    error_code = "model_call_failed"
                elif response.get("mode") != capability.route_mode:
                    error_code = "route_mismatch"
                elif response.get("chat_model_id") != capability.model_id:
                    error_code = "model_identity_mismatch"
            except Exception:
                error_code = "model_adapter_exception"
            latency_ms = max(0, round((timer_ns() - started_ns) / 1_000_000))
            result = score_chat_model_task_response(
                route_mode=capability.route_mode,
                task_id=task.task_id,
                response_text=response_text,
                latency_ms=latency_ms,
                error_code=error_code,
            )
            results.append(result)
            logger.info(
                "CHAT_MODEL_TASK_BENCHMARK_CALL_COMPLETED",
                extra={
                    "event": "CHAT_MODEL_TASK_BENCHMARK_CALL_COMPLETED",
                    "benchmark_version": CHAT_MODEL_TASK_BENCHMARK_VERSION,
                    "route_mode": result.route_mode,
                    "model_id": result.model_id,
                    "task_id": result.task_id,
                    "task_class": result.task_class,
                    "score": result.score,
                    "passed": result.passed,
                    "latency_ms": result.latency_ms,
                    "error_code": result.error_code,
                },
            )
    return chat_model_task_benchmark_payload(results, model_calls=len(results))


def chat_model_task_benchmark_payload(
    results: Sequence[ChatModelTaskBenchmarkResult],
    *,
    model_calls: int,
) -> dict[str, object]:
    rows = [result.metadata() for result in results]
    scorecards: list[dict[str, object]] = []
    for capability in DEFAULT_CHAT_MODEL_CAPABILITIES:
        model_results = [
            result for result in results if result.route_mode == capability.route_mode
        ]
        if not model_results:
            continue
        passed = sum(result.passed for result in model_results)
        average_score = round(
            sum(result.score for result in model_results) / len(model_results), 1
        )
        average_latency_ms = round(
            sum(result.latency_ms for result in model_results) / len(model_results)
        )
        scorecards.append(
            {
                "route_mode": capability.route_mode,
                "provider": capability.provider,
                "model_id": capability.model_id,
                "deployment": capability.deployment,
                "privacy_tier": capability.privacy_tier,
                "cost_tier": capability.cost_tier,
                "average_score": average_score,
                "pass_rate": round(passed / len(model_results), 3),
                "average_latency_ms": average_latency_ms,
                "tasks": {
                    result.task_class: {
                        "task_id": result.task_id,
                        "score": result.score,
                        "registry_task_score": result.registry_task_score,
                        "score_delta": result.score - result.registry_task_score,
                        "passed": result.passed,
                        "latency_ms": result.latency_ms,
                    }
                    for result in model_results
                },
            }
        )
    failed = sum(not result.passed for result in results)
    return {
        "schema_version": CHAT_MODEL_TASK_BENCHMARK_SCHEMA_VERSION,
        "benchmark_version": CHAT_MODEL_TASK_BENCHMARK_VERSION,
        "registry_version": CHAT_MODEL_CAPABILITY_REGISTRY_VERSION,
        "status": "failed" if failed else "passed",
        "advisory_only": True,
        "routing_scores_mutated": False,
        "passed": len(results) - failed,
        "failed": failed,
        "scorecards": scorecards,
        "results": rows,
        "reporting": {
            "model_calls": model_calls,
            "raw_prompts_retained": False,
            "raw_responses_retained": False,
        },
    }


def _selected_capabilities(
    route_modes: Sequence[str],
) -> tuple[ChatModelCapability, ...]:
    requested = tuple(dict.fromkeys(mode.lower() for mode in route_modes))
    if not requested:
        raise ValueError("at least one route mode is required")
    capabilities: list[ChatModelCapability] = []
    for route_mode in requested:
        capability = get_chat_model_capability(route_mode)
        if capability is None:
            raise ValueError(f"unknown route mode: {route_mode}")
        capabilities.append(capability)
    return tuple(capabilities)


def _selected_tasks(
    task_ids: Sequence[str] | None,
) -> tuple[ChatModelBenchmarkTask, ...]:
    if task_ids is None:
        return DEFAULT_CHAT_MODEL_BENCHMARK_TASKS
    requested = tuple(dict.fromkeys(task_ids))
    if not requested:
        raise ValueError("at least one task is required")
    return tuple(_task_by_id(task_id) for task_id in requested)


def _task_by_id(task_id: str) -> ChatModelBenchmarkTask:
    task = next(
        (
            item
            for item in DEFAULT_CHAT_MODEL_BENCHMARK_TASKS
            if item.task_id == task_id
        ),
        None,
    )
    if task is None:
        raise ValueError(f"unknown benchmark task: {task_id}")
    return task


def _check_passed(check: ChatModelBenchmarkCheck, response_text: str) -> bool:
    normalized = response_text.casefold()
    terms = tuple(term.casefold() for term in check.terms)
    if check.kind == "contains_all":
        return all(term in normalized for term in terms)
    if check.kind == "excludes_all":
        return all(term not in normalized for term in terms)
    if check.kind == "ordered":
        positions = [normalized.find(term) for term in terms]
        return all(position >= 0 for position in positions) and positions == sorted(
            positions
        )
    if check.kind == "json_equals":
        return _parsed_json(response_text) == check.expected_json
    return False


def _parsed_json(response_text: str) -> object:
    value = response_text.strip()
    if value.startswith("```") and value.endswith("```"):
        lines = value.splitlines()
        value = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _normalized_error_code(error_code: str | None) -> str | None:
    if not error_code:
        return None
    return error_code if error_code in _ALLOWED_ERROR_CODES else "model_call_failed"
