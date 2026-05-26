"""Registry governance checks for skill and agent catalog drift."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from brain.registry.models import SkillSpec

ROUTE_OWNED_EXECUTION_PATH = "fastapi_route"
APPROVAL_REQUIRED_TIERS = {"T4", "T5"}


@dataclass(frozen=True, slots=True)
class SkillHandlerCoverageReport:
    missing_active_handlers: list[str] = field(default_factory=list)
    orphan_handlers: list[str] = field(default_factory=list)
    active_high_risk_without_bridge: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (
            self.missing_active_handlers
            or self.orphan_handlers
            or self.active_high_risk_without_bridge
        )


def evaluate_skill_handler_coverage(
    skills: Iterable[SkillSpec],
    handlers: Mapping[str, Any],
) -> SkillHandlerCoverageReport:
    """Check that active SkillRunner skills have handlers and no handler drifts.

    Some "skills" are route-owned governance surfaces, such as Mattermost
    slash-command reads. They are still tracked in the registry, but they do not
    execute through SkillRunner and must opt out explicitly with
    ``metadata.execution_path = fastapi_route``.
    """

    skill_by_name = {skill.name: skill for skill in skills}
    handler_names = set(handlers)
    missing_active_handlers: list[str] = []
    active_high_risk_without_bridge: list[str] = []

    for skill in skill_by_name.values():
        if skill.status != "active":
            continue
        execution_path = skill.metadata.get("execution_path", "skill_runner")
        if execution_path == ROUTE_OWNED_EXECUTION_PATH:
            continue
        if skill.name not in handler_names:
            missing_active_handlers.append(skill.name)
        if (
            skill.approval_tier in APPROVAL_REQUIRED_TIERS
            and skill.metadata.get("approval_queue_bridge") != "enabled"
        ):
            active_high_risk_without_bridge.append(skill.name)

    orphan_handlers = sorted(handler_names - set(skill_by_name))
    return SkillHandlerCoverageReport(
        missing_active_handlers=sorted(missing_active_handlers),
        orphan_handlers=orphan_handlers,
        active_high_risk_without_bridge=sorted(active_high_risk_without_bridge),
    )


def assert_skill_handler_coverage(
    skills: Iterable[SkillSpec],
    handlers: Mapping[str, Any],
) -> None:
    report = evaluate_skill_handler_coverage(skills, handlers)
    if report.ok:
        return
    raise AssertionError(
        "skill handler coverage failed: "
        f"missing_active_handlers={report.missing_active_handlers}; "
        f"orphan_handlers={report.orphan_handlers}; "
        "active_high_risk_without_bridge="
        f"{report.active_high_risk_without_bridge}"
    )
