"""Answer-engine UX contract evals for Beacon.

These checks stay offline and deterministic. They verify the contracts the UI
surfaces to operators: focus modes, citation support, refusal behavior, provider
strategy, and deep-research coverage.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from brain.services.internet_scout.models import (
    InternetScoutRequest,
    InternetTool,
)
from brain.services.internet_scout.orchestrator import InternetScoutOrchestrator
from brain.services.internet_scout.search_quality_evals import (
    SearchQualityEvalResult,
    run_search_quality_evals,
)


@dataclass(frozen=True)
class AnswerEngineEvalResult:
    name: str
    eval_group: str
    passed: bool
    details: dict[str, object]
    failures: tuple[str, ...] = ()


def run_answer_engine_evals() -> list[AnswerEngineEvalResult]:
    """Run the Beacon answer-engine UX contract benchmark."""
    search_results = run_search_quality_evals()
    by_name = {result.name: result for result in search_results}
    return [
        *_focus_mode_contract_results(),
        _quality_suite_coverage(search_results),
        _citation_surface_contract(by_name),
        _refusal_contract(by_name),
        _deep_research_contract(by_name),
        _provider_telemetry_contract(by_name),
        _evidence_transparency_contract(by_name),
    ]


def answer_engine_eval_payload() -> dict[str, object]:
    """Return a JSON-safe payload for scripts, CI, and health wiring."""
    results = run_answer_engine_evals()
    failed = [result for result in results if not result.passed]
    return {
        "suite": "beacon_answer_engine",
        "suite_version": 1,
        "status": "failed" if failed else "passed",
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "case_groups": _group_summary(results),
        "results": [
            {
                **asdict(result),
                "failures": list(result.failures),
            }
            for result in results
        ],
    }


def _focus_mode_contract_results() -> list[AnswerEngineEvalResult]:
    cases = [
        (
            "focus_mode_official_forces_authority",
            InternetScoutRequest(
                query="OpenAI Responses API docs",
                tool_hint=InternetTool.SEARCH,
                focus_mode="official",
                max_pages=2,
                requester="alpha_ui.beacon_answer_engine",
            ),
            {
                "intent": "official_docs",
                "authority_required": True,
                "provider_strategy": "fanout",
                "expected_source_types": ("official_docs", "primary_source"),
            },
        ),
        (
            "focus_mode_deep_research_fans_out",
            InternetScoutRequest(
                query="compare Brave Search API and Perplexity Search API",
                tool_hint=InternetTool.SEARCH,
                focus_mode="deep_research",
                max_pages=4,
                requester="alpha_ui.beacon_answer_engine",
            ),
            {
                "provider_strategy": "fanout",
                "min_searches": 3,
                "min_extracts": 2,
                "min_subquestions": 3,
            },
        ),
        (
            "focus_mode_local_weather_marks_freshness",
            InternetScoutRequest(
                query="weather right now",
                tool_hint=InternetTool.SEARCH,
                focus_mode="local_weather",
                requester="alpha_ui.beacon_answer_engine",
            ),
            {
                "intent": "current_fact",
                "freshness_required": True,
            },
        ),
        (
            "focus_mode_shopping_tracks_pricing",
            InternetScoutRequest(
                query="best current price for Mac mini",
                tool_hint=InternetTool.SEARCH,
                focus_mode="shopping",
                requester="alpha_ui.beacon_answer_engine",
            ),
            {
                "freshness_required": True,
                "primary_source_required": True,
                "expected_source_types": ("pricing",),
            },
        ),
        (
            "focus_mode_academic_requires_primary_sources",
            InternetScoutRequest(
                query="single kidney pediatric sports guidance",
                tool_hint=InternetTool.SEARCH,
                focus_mode="academic",
                max_pages=2,
                requester="alpha_ui.beacon_answer_engine",
            ),
            {
                "primary_source_required": True,
                "provider_strategy": "fanout",
                "expected_source_types": ("primary_source", "trusted_secondary"),
            },
        ),
    ]
    return [_run_focus_mode_case(*case) for case in cases]


def _run_focus_mode_case(
    name: str,
    request: InternetScoutRequest,
    expected: dict[str, object],
) -> AnswerEngineEvalResult:
    plan = InternetScoutOrchestrator().plan(request).research
    failures: list[str] = []
    if expected.get("intent") is not None and plan.intent != expected["intent"]:
        failures.append(f"intent:{plan.intent}")
    if expected.get("authority_required") is not None and (
        plan.authority_required is not expected["authority_required"]
    ):
        failures.append("authority_required")
    if expected.get("freshness_required") is not None and (
        plan.freshness_required is not expected["freshness_required"]
    ):
        failures.append("freshness_required")
    if expected.get("primary_source_required") is not None and (
        plan.primary_source_required is not expected["primary_source_required"]
    ):
        failures.append("primary_source_required")
    if expected.get("provider_strategy") is not None and (
        plan.provider_strategy != expected["provider_strategy"]
    ):
        failures.append(f"provider_strategy:{plan.provider_strategy}")
    if len(plan.searches) < int(expected.get("min_searches", 0)):
        failures.append("search_budget")
    if plan.max_extracts < int(expected.get("min_extracts", 0)):
        failures.append("extract_budget")
    if len(plan.subquestions) < int(expected.get("min_subquestions", 0)):
        failures.append("subquestion_count")
    missing_source_types = set(expected.get("expected_source_types", ())) - set(
        plan.expected_source_types
    )
    if missing_source_types:
        failures.append(f"expected_source_types:{sorted(missing_source_types)}")
    if f"focus_mode:{request.focus_mode}" not in plan.notes:
        failures.append("focus_mode_note")

    return AnswerEngineEvalResult(
        name=name,
        eval_group="focus_modes",
        passed=not failures,
        details={
            "focus_mode": request.focus_mode,
            "intent": plan.intent,
            "authority_required": plan.authority_required,
            "freshness_required": plan.freshness_required,
            "primary_source_required": plan.primary_source_required,
            "provider_strategy": plan.provider_strategy,
            "search_count": len(plan.searches),
            "max_extracts": plan.max_extracts,
            "subquestion_count": len(plan.subquestions),
            "expected_source_types": plan.expected_source_types,
            "notes": plan.notes,
        },
        failures=tuple(failures),
    )


def _quality_suite_coverage(
    results: list[SearchQualityEvalResult],
) -> AnswerEngineEvalResult:
    groups = {result.eval_group for result in results}
    failures: list[str] = []
    if len(results) < 30:
        failures.append("case_count")
    if any(not result.passed for result in results):
        failures.append("search_quality_failures")
    if "daily_use" not in groups:
        failures.append("daily_use_group")
    return AnswerEngineEvalResult(
        name="quality_suite_coverage",
        eval_group="benchmark_breadth",
        passed=not failures,
        details={
            "case_count": len(results),
            "groups": sorted(groups),
            "failed": [result.name for result in results if not result.passed],
        },
        failures=tuple(failures),
    )


def _citation_surface_contract(
    results: dict[str, SearchQualityEvalResult],
) -> AnswerEngineEvalResult:
    official = results["official_openai_source_beats_community"]
    details = official.details
    failures: list[str] = []
    if details["status"] != "supported":
        failures.append("status")
    if details["accepted_hosts"] != ["platform.openai.com"]:
        failures.append("accepted_hosts")
    if details["official_source_count"] < 1:
        failures.append("official_source_count")
    if details["synthesis_required_behavior"] != "answer_with_citations":
        failures.append("synthesis_behavior")
    if not str(details["answer_context"]).strip():
        failures.append("answer_context")
    return AnswerEngineEvalResult(
        name="citation_surface_has_ranked_supported_sources",
        eval_group="citation_surface",
        passed=not failures,
        details={
            "status": details["status"],
            "accepted_hosts": details["accepted_hosts"],
            "official_source_count": details["official_source_count"],
            "synthesis_required_behavior": details["synthesis_required_behavior"],
            "answer_context_present": bool(str(details["answer_context"]).strip()),
        },
        failures=tuple(failures),
    )


def _refusal_contract(
    results: dict[str, SearchQualityEvalResult],
) -> AnswerEngineEvalResult:
    names = [
        "unsupported_official_pricing_claim_fails_closed",
        "prompt_injection_marker_rejects_citation",
        "negated_claim_mismatch_fails_closed",
    ]
    failures = [
        name
        for name in names
        if results[name].details["status"] != "insufficient"
        or results[name].details["synthesis_answerable"] is not False
    ]
    return AnswerEngineEvalResult(
        name="insufficient_evidence_refuses_cleanly",
        eval_group="refusal_quality",
        passed=not failures,
        details={
            name: {
                "status": results[name].details["status"],
                "synthesis_answerable": results[name].details["synthesis_answerable"],
            }
            for name in names
        },
        failures=tuple(failures),
    )


def _deep_research_contract(
    results: dict[str, SearchQualityEvalResult],
) -> AnswerEngineEvalResult:
    case = results["official_vendor_comparison_prefers_provider_docs"]
    details = case.details
    failures: list[str] = []
    if details["research_stop_criteria"]["require_cross_check"] is not True:
        failures.append("cross_check")
    if details["research_subquestion_count"] < 3:
        failures.append("subquestions")
    if details["research_report_answerability"] != "answerable":
        failures.append("answerability")
    if details["research_report_cited_source_count"] < 2:
        failures.append("source_count")
    if (
        details["covered_official_target_count"]
        < details["required_official_target_count"]
    ):
        failures.append("official_target_coverage")
    if len(details["research_report_verified_claims"]) < 2:
        failures.append("verified_claims")
    if details["research_report_unsupported_claims"]:
        failures.append("unsupported_claims")
    if details["research_report_coverage_warnings"]:
        failures.append("coverage_warnings")
    return AnswerEngineEvalResult(
        name="deep_research_surfaces_plan_and_coverage",
        eval_group="deep_research",
        passed=not failures,
        details={
            "research_subquestion_count": details["research_subquestion_count"],
            "research_stop_criteria": details["research_stop_criteria"],
            "research_report_answerability": details["research_report_answerability"],
            "research_report_cited_source_count": details[
                "research_report_cited_source_count"
            ],
            "required_official_target_count": details["required_official_target_count"],
            "covered_official_target_count": details["covered_official_target_count"],
            "research_report_verified_claims": details[
                "research_report_verified_claims"
            ],
            "research_report_unsupported_claims": details[
                "research_report_unsupported_claims"
            ],
            "research_report_coverage_warnings": details[
                "research_report_coverage_warnings"
            ],
        },
        failures=tuple(failures),
    )


def _provider_telemetry_contract(
    results: dict[str, SearchQualityEvalResult],
) -> AnswerEngineEvalResult:
    case = results["official_openai_source_beats_community"]
    details = case.details
    failures: list[str] = []
    if details["research_provider_strategy"] != "fanout":
        failures.append("provider_strategy")
    if details["research_search_providers"] != ["searxng", "brave", "perplexity"]:
        failures.append("provider_order")
    if details["research_search_budget"] < 3:
        failures.append("search_budget")
    return AnswerEngineEvalResult(
        name="provider_route_and_budget_are_visible",
        eval_group="provider_telemetry",
        passed=not failures,
        details={
            "provider_strategy": details["research_provider_strategy"],
            "search_providers": details["research_search_providers"],
            "search_budget": details["research_search_budget"],
            "max_extracts": details["research_max_extracts"],
        },
        failures=tuple(failures),
    )


def _evidence_transparency_contract(
    results: dict[str, SearchQualityEvalResult],
) -> AnswerEngineEvalResult:
    official = results["official_openai_source_beats_community"]
    unsupported = results["unsupported_official_pricing_claim_fails_closed"]
    current = results["current_fact_report_carries_plan_and_freshness_coverage"]
    official_transparency = official.details["evidence_transparency"]
    unsupported_transparency = unsupported.details["evidence_transparency"]
    current_transparency = current.details["evidence_transparency"]

    official_accepted = official_transparency["accepted_sources"]
    official_rejected = official_transparency["rejected_sources"]
    unsupported_rejected = unsupported_transparency["rejected_sources"]
    current_accepted = current_transparency["accepted_sources"]
    official_score = official_transparency.get("answer_quality_score", {})
    failures: list[str] = []

    if not official_accepted or official_accepted[0]["official_host_match"] is not True:
        failures.append("accepted_official_host_match")
    if not official_rejected:
        failures.append("rejected_sources")
    else:
        rejected = official_rejected[0]
        if rejected["host"] != "community.openai.com":
            failures.append("rejected_host")
        if "official_host_mismatch" not in rejected["rejection_reasons"]:
            failures.append("official_mismatch_reason")
    if not unsupported_rejected:
        failures.append("unsupported_rejected_source")
    else:
        unsupported_item = unsupported_rejected[0]
        if unsupported_item["claim_supported"] is not False:
            failures.append("claim_supported_flag")
        if not unsupported_item["claim_support_reasons"]:
            failures.append("claim_support_reasons")
    if current_transparency["freshness_required"] is not True:
        failures.append("freshness_required")
    if not current_accepted or not current_accepted[0].get("fetched_at"):
        failures.append("fetched_at")
    if official_score.get("score", 0) < 80:
        failures.append("answer_quality_score")
    if official_score.get("rejected_risk_count", 0) < 1:
        failures.append("answer_quality_rejected_risk_count")

    return AnswerEngineEvalResult(
        name="evidence_transparency_surfaces_operator_decisions",
        eval_group="evidence_transparency",
        passed=not failures,
        details={
            "official_accepted_hosts": [item["host"] for item in official_accepted],
            "official_rejected_hosts": [item["host"] for item in official_rejected],
            "official_rejection_reasons": (
                official_rejected[0]["rejection_reasons"] if official_rejected else []
            ),
            "unsupported_claim_support_reasons": (
                unsupported_rejected[0]["claim_support_reasons"]
                if unsupported_rejected
                else []
            ),
            "freshness_required": current_transparency["freshness_required"],
            "current_fetched_at_present": bool(
                current_accepted and current_accepted[0].get("fetched_at")
            ),
            "answer_quality_score": official_score,
        },
        failures=tuple(failures),
    )


def _group_summary(results: list[AnswerEngineEvalResult]) -> dict[str, object]:
    groups: dict[str, list[AnswerEngineEvalResult]] = {}
    for result in results:
        groups.setdefault(result.eval_group, []).append(result)
    return {
        name: {
            "case_count": len(items),
            "passed": sum(1 for item in items if item.passed),
            "failed": sum(1 for item in items if not item.passed),
            "failure_names": [item.name for item in items if not item.passed],
            "case_names": [item.name for item in items],
        }
        for name, items in sorted(groups.items())
    }
