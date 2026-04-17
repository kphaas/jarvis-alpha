"""Multi-signal Dream Mode kill switch.

Three independent kill signals — ANY ONE disables Dream Mode:

1. Environment: DREAM_MODE_ENABLED must be truthy
2. DB flag: alpha_system_flags.dream_mode_killed must be FALSE
3. Per-step cost governor: handled by dream_cost_cap_service (already built)

Usage:
    from gateway.dream.kill_switch import (
        is_dream_mode_enabled,     # env check only (sync, fast)
        is_killed_in_db,           # DB check (async, per-step)
        assert_can_run,            # combined env + DB check for startup
    )

Fail-closed everywhere — any check failure = DISABLED.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import asyncpg

log = logging.getLogger(__name__)

ENABLED_VALUES = {"true", "1", "yes", "on"}
ENV_VAR = "DREAM_MODE_ENABLED"


def is_dream_mode_enabled() -> bool:
    """Env-var check. Returns True only if DREAM_MODE_ENABLED is explicitly truthy.

    Fail-closed: any other value (unset, '', 'false', '0', etc.) = False.
    Called at orchestrator startup.
    """
    raw = os.environ.get(ENV_VAR, "").strip().lower()
    enabled = raw in ENABLED_VALUES
    log.info(
        "dream_kill_switch env_check: env=%s raw=%r enabled=%s",
        ENV_VAR,
        raw,
        enabled,
    )
    return enabled


async def is_killed_in_db(pool: asyncpg.Pool) -> bool:
    """DB flag check. Returns True if dream_mode_killed flag is set.

    Fail-closed: DB error = treat as killed (safer than running blind).
    Called before each dream step.
    """
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "SELECT set_config('jarvis.role', 'platform_admin', true)"
                )
                row = await conn.fetchrow(
                    """
                    SELECT flag_value FROM alpha_system_flags
                    WHERE flag_name = 'dream_mode_killed'
                    """
                )
        if row is None:
            log.warning(
                "dream_kill_switch db_check: flag row missing — treating as killed"
            )
            return True
        killed = bool(row["flag_value"])
        if killed:
            log.warning("dream_kill_switch db_check: KILLED flag is TRUE")
        return killed
    except Exception as e:
        log.error("dream_kill_switch db_check failed, fail-closed: %s", e)
        return True


async def assert_can_run(pool: Optional[asyncpg.Pool] = None) -> None:
    """Combined startup assertion. Raises RuntimeError if any signal disables Dream Mode.

    If pool is None, only env check runs (startup phase before pool ready).
    If pool is provided, both env and DB are checked.
    """
    if not is_dream_mode_enabled():
        raise RuntimeError(
            f"Dream Mode is DISABLED via {ENV_VAR} env kill switch — refusing to run"
        )
    if pool is not None:
        killed = await is_killed_in_db(pool)
        if killed:
            raise RuntimeError(
                "Dream Mode is DISABLED via DB flag alpha_system_flags.dream_mode_killed"
            )


# Back-compat alias for callers that used assert_enabled()
assert_enabled = is_dream_mode_enabled
