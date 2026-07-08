"""
CI gate — fails if any mounted route is unclassified.

Run: python3 -m pytest tests/test_route_classification.py -v
"""

from brain.app import app
from brain.middleware.approval_audit import audit_route_classifications
from brain.middleware.approval_classes import classify_route, determine_risk_tier


def test_all_routes_classified():
    """Every mounted route must have a classification in ROUTE_CLASSIFICATION."""
    unclassified = audit_route_classifications(app)
    assert unclassified == [], (
        f"Unclassified routes found (will default to T5 deny): {unclassified}"
    )


def test_semantic_memory_update_route_is_classified_write():
    classes = classify_route("PATCH", "/v1/memory/semantic/{memory_id}")

    assert classes == ["write"]
    assert determine_risk_tier(classes) == "T2"


def test_temporal_graph_memory_routes_are_classified():
    read_classes = classify_route("GET", "/v1/memory/admin/users/{principal_id}/graph")
    propose_classes = classify_route("POST", "/v1/memory/graph/proposals")
    execute_classes = classify_route(
        "POST",
        "/v1/memory/graph/proposals/{proposal_id}/execute",
    )

    assert read_classes == ["read", "security_read"]
    assert determine_risk_tier(read_classes) == "T2"
    assert propose_classes == ["write"]
    assert determine_risk_tier(propose_classes) == "T2"
    assert execute_classes == ["write"]
    assert determine_risk_tier(execute_classes) == "T2"


def test_chat_outcome_audit_route_is_security_read():
    classes = classify_route("GET", "/v1/chat/outcomes")

    assert classes == ["read", "security_read"]
    assert determine_risk_tier(classes) == "T2"
