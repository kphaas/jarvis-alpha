"""Privacy-scrub agent runner.

P1: No-op stub. Wires the integration point but does no work.

Plugs into brain/agents/buddy_agent.py:_maybe_run_managed_agents()
starting in P2 once the inventory scanner is implemented. Pattern
mirrors brain/agents/chatops_smoke.py and network_watchdog.py.

P2 will replace the no-op body with:
    1. List active subjects (alpha_privacy_subjects WHERE status='active').
    2. For each subject, compute next scan due date.
    3. If due, enqueue scan into TaskGraph (or run inline if synchronous).
    4. Write progress to alpha_buddy_events as 'system' priority=1.
"""

from __future__ import annotations

import os

import asyncpg

from jarvis_common.logging_config import get_logger

logger = get_logger("privacy_scrub.runner")

# Default OFF — P1 stays inert even if the runner is plugged in early.
PRIVACY_SCRUB_ENABLED = os.environ.get("PRIVACY_SCRUB_ENABLED", "0") == "1"


async def maybe_run_privacy_scrub(pool: asyncpg.Pool) -> None:
    """No-op runner. Returns immediately unless explicitly enabled."""
    if not PRIVACY_SCRUB_ENABLED:
        return

    # P1 still does no work even if enabled — this is a wiring smoke test.
    logger.info("privacy_scrub_tick stub=true note='P2 will replace this body'")
