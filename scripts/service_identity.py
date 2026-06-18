"""Service identity constants — single source of truth.

Used by gen_service_token.py and rotate_service_token.py.
Do not duplicate these constants elsewhere.
"""

VALID_ISS_ACTOR_PAIRS = {
    "brain": "service",
    "forge": "service",
    "gateway": "service",
    "sandbox": "service",
    "buddy": "agent",
    "endpoint": "service",
    "print": "service",
}

DEFAULT_SCOPES = {
    "brain": ["service.internal", "health.read", "cloud.call"],
    "forge": [
        "forge.llm.call",
        "forge.briefings.ingest",
        "briefings.read",
        "health.read",
    ],
    "buddy": [
        "memory.evict",
        "memory.promote",
        "tasks.scan",
        "buddy.events.write",
        "health.read",
    ],
    "gateway": [
        "dream.execute",
        "dream.plan",
        "dream.review",
        "cloud.call",
        "dream.kill",
        "cost.report",
        "health.read",
    ],
    "sandbox": [
        "forge.deploy.submit",
        "forge.costs.report",
        "forge.llm.call",
        "health.read",
    ],
    "endpoint": ["health.read", "school_email.read", "vault.write"],
    # Least-privilege: print may only call the internal LLM completion route.
    "print": ["llm:complete"],
}

TOKEN_LIFETIME_DAYS = 7
