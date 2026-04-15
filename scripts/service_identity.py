"""Service identity constants — single source of truth.

Used by gen_service_token.py and rotate_service_token.py.
Do not duplicate these constants elsewhere.
"""

VALID_ISS_ACTOR_PAIRS = {
    "brain":    "service",
    "gateway":  "service",
    "sandbox":  "service",
    "buddy":    "agent",
    "endpoint": "service",
}

DEFAULT_SCOPES = {
    "brain":    ["service.internal", "health.read"],
    "buddy":    ["memory.evict", "memory.promote", "tasks.scan", "buddy.events.write", "health.read"],
    "gateway":  ["dream.execute", "cloud.call", "dream.kill", "health.read"],
    "sandbox": ["forge.deploy.submit", "forge.costs.report", "forge.llm.call", "health.read"],
    "endpoint": ["health.read"],
}

TOKEN_LIFETIME_DAYS = 1
