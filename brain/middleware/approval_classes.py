"""
Route classification registry for Approval Gateway.

Every API route is classified by action classes, which determine risk tier.
Unclassified routes default to T5 (deny by default).
"""

# Action class → route mapping
# Lookup is method + longest prefix match
ROUTE_CLASSIFICATION: dict[str, list[str]] = {
    # Reads — T1
    "GET /health": ["read"],
    "GET /v1/mesh/status": ["read"],
    "GET /v1/home/summary": ["read"],
    "GET /v1/buddy/events": ["read"],
    "GET /v1/costs/summary": ["read"],
    "GET /v1/unifi/status": ["read"],
    "GET /v1/unifi/wan": ["read"],
    "GET /v1/unifi/clients": ["read"],
    "GET /v1/unifi/summary": ["read"],
    "GET /v1/tasks/graphs": ["read"],
    "GET /v1/approval": ["read"],
    # Writes — T2
    "POST /v1/tasks/ingest": ["write"],
    "POST /v1/memory": ["write"],
    "PATCH /v1/tasks": ["write"],
    # Chat — varies by model routing (local=write, cloud=external_call+cost)
    # Default to write — cloud escalation handled at route level
    "POST /v1/chat": ["write"],
    "PUT /v1/chat": ["write"],
    "DELETE /v1/chat": ["write"],
    # Ask — always involves potential cloud call
    "POST /v1/ask": ["write", "external_call", "cost_incurring"],
    # Cloud calls — T3
    "POST /v1/cloud/call": ["external_call", "cost_incurring"],
    # Dream mode — controlled by scopes, but classify for audit
    "POST /v1/dream": ["write", "external_call", "cost_incurring"],
    "PATCH /v1/dream": ["write"],
    "DELETE /v1/dream": ["write"],
    # Auth — admin
    "POST /v1/auth/set-child-pin": ["admin"],
    # Admin
    "POST /v1/admin": ["admin"],
    # Destructive
    "DELETE /v1/memory": ["destructive"],
    # Approval routes themselves — read/write
    "POST /v1/approval/request": ["write"],
    "GET /v1/approval/{id}/status": ["read"],
    "POST /v1/approval/{id}/decide": ["admin"],
    # Honeypot
    "POST /v1/honeypot": ["write"],
    "GET /v1/honeypot": ["read"],
}


# Tier assignment rules (order matters — first match wins)
# Each rule: (required_classes, tier)
# If action has ALL required_classes, that tier applies
TIER_RULES: list[tuple[set[str], str]] = [
    # Compound high-risk first
    ({"deploy", "child_facing"}, "T5"),
    ({"unclassified"}, "T5"),
    ({"destructive"}, "T5"),
    ({"admin"}, "T5"),
    ({"deploy"}, "T4"),
    ({"child_facing"}, "T4"),
    ({"cost_incurring"}, "T3"),
    ({"external_call"}, "T2"),
    ({"write"}, "T2"),
    ({"read"}, "T1"),
]


def classify_route(method: str, path: str) -> list[str]:
    """Classify a route by method + longest prefix match.

    Returns action classes list. Unregistered routes return ["unclassified"].
    """
    method = method.upper()

    # Exact match first
    key = f"{method} {path}"
    if key in ROUTE_CLASSIFICATION:
        return ROUTE_CLASSIFICATION[key]

    # Longest prefix match — strip path segments from the right
    # e.g., "GET /v1/approval/abc-123/status" matches "GET /v1/approval/{id}/status"
    # But we can't match {id} literally — so match by prefix up to the parameterized segment
    best_match: str | None = None
    best_length = 0
    for registered_key, classes in ROUTE_CLASSIFICATION.items():
        reg_method, reg_path = registered_key.split(" ", 1)
        if reg_method != method:
            continue
        # Check if the registered path is a prefix of the request path
        # Handle parameterized paths: /v1/approval/{id}/status
        # Strip {param} segments and compare prefixes
        reg_segments = reg_path.strip("/").split("/")
        req_segments = path.strip("/").split("/")

        if len(reg_segments) > len(req_segments):
            continue

        match = True
        for i, seg in enumerate(reg_segments):
            if seg.startswith("{") and seg.endswith("}"):
                continue  # wildcard segment — matches anything
            if seg != req_segments[i]:
                match = False
                break

        if match and len(reg_segments) > best_length:
            best_length = len(reg_segments)
            best_match = registered_key

    if best_match:
        return ROUTE_CLASSIFICATION[best_match]

    return ["unclassified"]


def determine_risk_tier(action_classes: list[str], overnight: bool = False) -> str:
    """Determine risk tier from action classes.

    Applies tier rules in priority order — first match wins.
    Overnight mode escalates T3 → budget-checked (handled by middleware, not here).
    T4/T5 overnight → always queued (handled by middleware).
    """
    class_set = set(action_classes)

    for required, tier in TIER_RULES:
        if required.issubset(class_set):
            return tier

    # Fallback — should never reach here if TIER_RULES covers all classes
    return "T5"
