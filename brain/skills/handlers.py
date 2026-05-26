"""Central SkillRunner handler map."""

from __future__ import annotations

from typing import Any

from brain.skills.notify import notify_skill_handlers
from brain.skills.obsidian import obsidian_skill_handlers
from brain.skills.unifi import unifi_skill_handlers


def all_skill_handlers() -> dict[str, Any]:
    """Return every provider adapter callable available to SkillRunner."""

    handlers: dict[str, Any] = {}
    for provider_handlers in (
        notify_skill_handlers(),
        unifi_skill_handlers(),
        obsidian_skill_handlers(),
    ):
        duplicate_names = set(handlers).intersection(provider_handlers)
        if duplicate_names:
            names = ", ".join(sorted(duplicate_names))
            raise RuntimeError(f"duplicate skill handlers registered: {names}")
        handlers.update(provider_handlers)
    return handlers
