"""
Route classification audit — logs warnings for any mounted route
not present in ROUTE_CLASSIFICATION.

Called once during Brain startup (lifespan hook).
"""

from fastapi import FastAPI
from brain.middleware.approval_classes import classify_route
from jarvis_common.logging_config import get_logger

logger = get_logger("alpha_brain")


def audit_route_classifications(app: FastAPI) -> list[str]:
    """Scan all mounted routes and warn about unclassified ones.

    Returns list of unclassified route keys for testing.
    """
    unclassified = []
    for route in app.routes:
        if not hasattr(route, "methods"):
            continue
        path = getattr(route, "path", "")
        if not path:
            continue
        for method in route.methods:
            classes = classify_route(method, path)
            if classes == ["unclassified"]:
                key = f"{method} {path}"
                unclassified.append(key)

    if unclassified:
        logger.warning(
            "ROUTE_AUDIT: %d unclassified route(s) — these default to T5 (deny): %s",
            len(unclassified),
            ", ".join(sorted(unclassified)),
        )
    else:
        logger.info("ROUTE_AUDIT: all %d routes classified", len(list(app.routes)))

    return unclassified
