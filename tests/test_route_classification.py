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
