"""Scheduled Beacon search-quality canary."""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from brain.services.internet_scout.models import InternetScoutRequest, InternetTool
from brain.services.internet_scout.orchestrator import InternetScoutOrchestrator
from brain.services.internet_scout.repository import InternetScoutRepository
from brain.services.internet_scout.search_quality_evals import (
    SearchQualityEvalResult,
    run_search_quality_evals,
)

BEACON_QUALITY_CANARY_REQUESTER = "alpha_beacon.quality_canary"
BEACON_QUALITY_CANARY_QUERY = "Beacon deterministic search quality canary"


async def run_quality_canary_once(conn) -> dict[str, object]:
    """Run the offline benchmark and persist redacted canary metadata."""
    results = run_search_quality_evals()
    failed = [result for result in results if not result.passed]
    status = "succeeded" if not failed else "failed"
    request = InternetScoutRequest(
        query=BEACON_QUALITY_CANARY_QUERY,
        tool_hint=InternetTool.SEARCH,
        max_pages=1,
        requester=BEACON_QUALITY_CANARY_REQUESTER,
    )
    plan = InternetScoutOrchestrator().plan(request)
    repo = InternetScoutRepository(conn)
    request_id = await repo.create_request(
        user_id="system",
        request=request,
        decision=plan.decision,
        status_override=status,
    )
    metadata = _quality_canary_metadata(results=results, request_id=request_id)
    await repo.record_tool_event(
        request_id=request_id,
        tool=plan.decision.tool.value,
        event_type="quality_canary",
        status=status,
        metadata=metadata,
    )
    return metadata


def _quality_canary_metadata(
    *,
    results: list[SearchQualityEvalResult],
    request_id: UUID,
) -> dict[str, object]:
    failed = [result for result in results if not result.passed]
    return {
        "suite": "beacon_search_quality",
        "suite_version": 2,
        "request_id": str(request_id),
        "status": "passed" if not failed else "failed",
        "case_count": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "failure_names": [result.name for result in failed[:20]],
        "failures": [
            {
                "name": result.name,
                "checks": list(result.failures),
            }
            for result in failed[:10]
        ],
        "case_names": [result.name for result in results],
    }


def search_quality_eval_payload() -> dict[str, object]:
    """Return the same benchmark payload used by scripts and tests."""
    results = run_search_quality_evals()
    failed = [result for result in results if not result.passed]
    return {
        "status": "failed" if failed else "passed",
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "results": [
            {
                **asdict(result),
                "failures": list(result.failures),
            }
            for result in results
        ],
    }
