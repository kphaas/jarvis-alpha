"""Deterministic Alpha chat quality eval harness."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from time import perf_counter_ns

from brain.routing.strategy import select_chat_strategy
from brain.services.chat_evidence_pack import (
    ChatEvidencePack,
    build_chat_evidence_pack,
    evaluate_chat_quality_gate,
    plan_chat_escalation,
    verify_chat_response,
)

CHAT_EVAL_SCHEMA_VERSION = "chat_eval_harness.v1"


@dataclass(frozen=True)
class ChatEvalResult:
    name: str
    eval_group: str
    passed: bool
    details: dict[str, object]
    failures: tuple[str, ...] = ()


def run_chat_eval_harness(
    outcomes: Sequence[Mapping[str, object]] = (),
) -> list[ChatEvalResult]:
    return [
        *_strategy_eval_results(),
        *_quality_gate_eval_results(),
        _outcome_audit_contract(outcomes),
    ]


def chat_eval_payload(
    outcomes: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    started_ns = perf_counter_ns()
    results = run_chat_eval_harness(outcomes)
    failed = [result for result in results if not result.passed]
    elapsed_ms = max(0, round((perf_counter_ns() - started_ns) / 1_000_000))
    return {
        "schema_version": CHAT_EVAL_SCHEMA_VERSION,
        "suite": "alpha_chat_quality",
        "suite_version": 1,
        "status": "failed" if failed else "passed",
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "case_groups": _group_summary(results),
        "scoreboard": _outcome_scoreboard(outcomes),
        "reporting": {
            "elapsed_ms": elapsed_ms,
            "model_calls": 0,
            "note": "Offline deterministic eval; stored outcomes are metadata-only.",
        },
        "results": [
            {
                **asdict(result),
                "failures": list(result.failures),
            }
            for result in results
        ],
    }


def _strategy_eval_results() -> list[ChatEvalResult]:
    cases = [
        {
            "name": "auto_short_prompt_uses_local",
            "prompt": "Draft a note.",
            "requested_model": "auto",
            "internet_mode": "none",
            "expected_strategy": "fast_local",
            "expected_route": "local",
        },
        {
            "name": "web_search_uses_grounded_strategy",
            "prompt": "Find the latest OpenAI API docs.",
            "requested_model": "auto",
            "internet_mode": "web_search",
            "expected_strategy": "grounded_local",
            "expected_model_prefix": "beacon/web_search",
        },
        {
            "name": "deep_research_uses_deep_verify",
            "prompt": "Compare current Claude and Gemini coding behavior.",
            "requested_model": "auto",
            "internet_mode": "deep_research",
            "expected_strategy": "deep_verify",
            "expected_model_prefix": "beacon/deep_research",
        },
        {
            "name": "manual_council_stays_council",
            "prompt": "Review this architecture decision.",
            "requested_model": "council",
            "internet_mode": "none",
            "council_models": ("claude", "gemini"),
            "expected_strategy": "council_light",
            "expected_route": "council",
        },
    ]
    return [_run_strategy_case(case) for case in cases]


def _run_strategy_case(case: Mapping[str, object]) -> ChatEvalResult:
    plan = select_chat_strategy(
        prompt=str(case["prompt"]),
        requested_model=str(case["requested_model"]),
        internet_mode=str(case["internet_mode"]),
        council_models=tuple(case.get("council_models", ())),
    )
    failures: list[str] = []
    if plan.strategy != case["expected_strategy"]:
        failures.append(f"strategy:{plan.strategy}")
    expected_route = case.get("expected_route")
    if expected_route and plan.route_mode != expected_route:
        failures.append(f"route:{plan.route_mode}")
    expected_model_prefix = case.get("expected_model_prefix")
    if expected_model_prefix and plan.model_path[:1] != (expected_model_prefix,):
        failures.append(f"model_path:{list(plan.model_path)}")

    return ChatEvalResult(
        name=str(case["name"]),
        eval_group="golden_strategy",
        passed=not failures,
        details={
            "strategy": plan.strategy,
            "route_mode": plan.route_mode,
            "model_path": list(plan.model_path),
            "reason": plan.reason,
        },
        failures=tuple(failures),
    )


def _quality_gate_eval_results() -> list[ChatEvalResult]:
    return [
        _run_quality_case(
            name="empty_response_retries_local",
            response_text="",
            evidence_pack=build_chat_evidence_pack(
                memory_context="", internet_context=None
            ),
            expected_action="replace_with_safe_fallback",
            expected_escalation="retry_local",
        ),
        _run_quality_case(
            name="unsupported_web_claim_requires_beacon",
            response_text="I checked the web and confirmed this.",
            evidence_pack=build_chat_evidence_pack(
                memory_context="", internet_context=None
            ),
            expected_action="replace_with_safe_fallback",
            expected_escalation="beacon",
        ),
        _run_quality_case(
            name="web_suggestion_requires_beacon",
            response_text="This needs current verification.",
            evidence_pack=build_chat_evidence_pack(
                memory_context="",
                internet_context=None,
                web_suggestion_context="Beacon has not run yet.",
            ),
            expected_action="require_beacon",
            expected_escalation="beacon",
        ),
        _run_quality_case(
            name="grounded_response_accepts",
            response_text="Beacon evidence supports the answer.",
            evidence_pack=build_chat_evidence_pack(
                memory_context="",
                internet_context="Citation-backed web context.",
                raw_web_content_is_untrusted=True,
            ),
            expected_action="accept",
            expected_escalation="none",
        ),
    ]


def _run_quality_case(
    *,
    name: str,
    response_text: str,
    evidence_pack: ChatEvidencePack,
    expected_action: str,
    expected_escalation: str,
) -> ChatEvalResult:
    verification = verify_chat_response(
        response_text=response_text,
        evidence_pack=evidence_pack,
    )
    gate = evaluate_chat_quality_gate(
        evidence_pack=evidence_pack,
        verification=verification,
    )
    escalation = plan_chat_escalation(quality_gate=gate)
    failures: list[str] = []
    if gate.action != expected_action:
        failures.append(f"action:{gate.action}")
    if escalation.rung != expected_escalation:
        failures.append(f"escalation:{escalation.rung}")

    return ChatEvalResult(
        name=name,
        eval_group="quality_gateway",
        passed=not failures,
        details={
            "action": gate.action,
            "passed": gate.passed,
            "reason": gate.reason,
            "escalation_rung": escalation.rung,
            "issue_count": len(verification.issues),
            "evidence_count": evidence_pack.evidence_count,
        },
        failures=tuple(failures),
    )


def _outcome_audit_contract(
    outcomes: Sequence[Mapping[str, object]],
) -> ChatEvalResult:
    failures: list[str] = []
    for index, outcome in enumerate(outcomes):
        schema = outcome.get("chat_outcome_schema_version")
        action = outcome.get("chat_outcome_quality_action")
        rung = outcome.get("chat_outcome_escalation_rung")
        if schema != "chat_outcome.v1":
            failures.append(f"row_{index}:schema")
        if action == "accept" and rung not in (None, "none"):
            failures.append(f"row_{index}:accept_escalated")
        if action != "accept" and not rung:
            failures.append(f"row_{index}:missing_escalation")

    return ChatEvalResult(
        name="stored_chat_outcomes_are_scorable",
        eval_group="outcome_audit",
        passed=not failures,
        details=_outcome_scoreboard(outcomes),
        failures=tuple(failures),
    )


def _outcome_scoreboard(
    outcomes: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    action_counts = Counter(
        str(outcome.get("chat_outcome_quality_action") or "unknown")
        for outcome in outcomes
    )
    route_counts = Counter(
        str(outcome.get("chat_outcome_route_mode") or "unknown") for outcome in outcomes
    )
    count = len(outcomes)
    accepted = action_counts.get("accept", 0)
    escalated = sum(
        1
        for outcome in outcomes
        if bool(outcome.get("chat_outcome_escalation_required"))
        or str(outcome.get("chat_outcome_escalation_rung") or "none") != "none"
    )
    council = sum(1 for outcome in outcomes if bool(outcome.get("used_council")))
    return {
        "evaluated_outcome_count": count,
        "accept_rate": round(accepted / count, 3) if count else None,
        "escalation_rate": round(escalated / count, 3) if count else None,
        "council_rate": round(council / count, 3) if count else None,
        "quality_actions": dict(sorted(action_counts.items())),
        "route_modes": dict(sorted(route_counts.items())),
    }


def _group_summary(results: Sequence[ChatEvalResult]) -> dict[str, dict[str, int]]:
    groups: dict[str, dict[str, int]] = {}
    for result in results:
        group = groups.setdefault(
            result.eval_group,
            {"case_count": 0, "passed": 0, "failed": 0},
        )
        group["case_count"] += 1
        group["passed" if result.passed else "failed"] += 1
    return groups
