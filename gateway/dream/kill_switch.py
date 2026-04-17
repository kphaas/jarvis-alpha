"""Dream Mode kill switch.

Reads DREAM_MODE_ENABLED from environment (sourced from ~/jarvis/.secrets).
Fail-closed: unset, empty, or anything other than 'true' = disabled.

Usage:
    from gateway.dream.kill_switch import is_dream_mode_enabled
    if not is_dream_mode_enabled():
        return  # refuse to run
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

ENABLED_VALUES = {"true", "1", "yes", "on"}
ENV_VAR = "DREAM_MODE_ENABLED"


def is_dream_mode_enabled() -> bool:
    """Returns True only if DREAM_MODE_ENABLED is explicitly truthy.

    Fail-closed: any other value (unset, '', 'false', '0', 'no', etc.) = False.
    Every call is logged so ops has audit trail of enforcement decisions.
    """
    raw = os.environ.get(ENV_VAR, "").strip().lower()
    enabled = raw in ENABLED_VALUES
    log.info(
        "dream_kill_switch check: env=%s raw=%r enabled=%s",
        ENV_VAR,
        raw,
        enabled,
    )
    return enabled


def assert_enabled() -> None:
    """Raise RuntimeError if kill switch is OFF. Orchestrator startup calls this."""
    if not is_dream_mode_enabled():
        raise RuntimeError(
            f"Dream Mode is DISABLED via {ENV_VAR} kill switch — refusing to run"
        )
