from __future__ import annotations

from brain.middleware.approval_classes import classify_route, determine_risk_tier


def test_memory_consolidation_proposal_route_passes_to_review_queue_bridge() -> None:
    classes = classify_route("POST", "/v1/memory/consolidation/proposals")

    assert classes == ["write"]
    assert "security_write" not in classes
    assert determine_risk_tier(classes) == "T2"


def test_memory_consolidation_execute_route_passes_to_proposal_bound_token() -> None:
    classes = classify_route(
        "POST",
        "/v1/memory/consolidation/proposals/11111111-1111-4111-8111-111111111111/execute",
    )

    assert classes == ["write"]
    assert "security_write" not in classes
    assert determine_risk_tier(classes) == "T2"


def test_memory_consolidation_revert_route_is_t5_not_security_write() -> None:
    classes = classify_route(
        "POST",
        "/v1/memory/consolidation/proposals/11111111-1111-4111-8111-111111111111/revert",
    )

    assert classes == ["memory_consolidation_reviewed_write"]
    assert "security_write" not in classes
    assert determine_risk_tier(classes) == "T5"


def test_unknown_memory_consolidation_action_fails_closed() -> None:
    classes = classify_route("POST", "/v1/memory/consolidation/unknown-action")

    assert classes == ["unclassified"]
    assert determine_risk_tier(classes) == "T5"
