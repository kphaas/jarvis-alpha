"""Central SkillRunner handler map."""

from __future__ import annotations

from typing import Any

from brain.skills.canary import canary_skill_handlers
from brain.skills.notify import notify_skill_handlers
from brain.skills.obsidian import obsidian_skill_handlers
from brain.skills.approval_bridge import SkillApprovalBridge
from brain.skills.runner import SkillRunner, SkillHandler
from brain.skills.secrets import secrets_skill_handlers
from brain.skills.unifi import unifi_skill_handlers
from brain.skills.weather import weather_skill_handlers


def all_skill_handlers() -> dict[str, Any]:
    """Return every provider adapter callable available to SkillRunner."""

    handlers: dict[str, Any] = {}
    for provider_handlers in (
        canary_skill_handlers(),
        notify_skill_handlers(),
        unifi_skill_handlers(),
        weather_skill_handlers(),
        obsidian_skill_handlers(),
        secrets_skill_handlers(),
    ):
        duplicate_names = set(handlers).intersection(provider_handlers)
        if duplicate_names:
            names = ", ".join(sorted(duplicate_names))
            raise RuntimeError(f"duplicate skill handlers registered: {names}")
        handlers.update(provider_handlers)
    return handlers


def build_skill_runner(
    handlers: dict[str, SkillHandler] | None = None,
) -> SkillRunner:
    """Return the production SkillRunner with approval queue bridge enabled."""

    return SkillRunner(
        handlers=handlers or all_skill_handlers(),
        approval_bridge=SkillApprovalBridge(),
    )
