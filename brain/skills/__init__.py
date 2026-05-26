"""Skill execution primitives."""

from brain.skills.approval_bridge import (
    SkillApprovalBridge,
    SkillApprovalItem,
    skill_parameters_hash,
)
from brain.skills.notify import (
    MattermostSkillError,
    MattermostSkillPayload,
    NotifySkillError,
    NotifySkillPayload,
    PushoverSkillError,
    PushoverSkillPayload,
    send_mattermost,
    send_notify,
    send_pushover,
)
from brain.skills.handlers import all_skill_handlers, build_skill_runner
from brain.skills.obsidian import (
    ObsidianSkillError,
    notes_search,
    obsidian_skill_handlers,
    tasks_create,
)
from brain.skills.policy_gate import (
    SkillInvocation,
    SkillPolicyDecision,
    SkillPolicyGate,
)
from brain.skills.runner import SkillCall, SkillRunResult, SkillRunner
from brain.skills.unifi import (
    UniFiSkillError,
    clients,
    health_check,
    unifi_skill_handlers,
    wan_status,
)

__all__ = [
    "SkillCall",
    "SkillInvocation",
    "SkillPolicyDecision",
    "SkillPolicyGate",
    "SkillRunner",
    "SkillRunResult",
    "all_skill_handlers",
    "build_skill_runner",
    "SkillApprovalBridge",
    "SkillApprovalItem",
    "skill_parameters_hash",
    "MattermostSkillError",
    "MattermostSkillPayload",
    "NotifySkillError",
    "NotifySkillPayload",
    "PushoverSkillError",
    "PushoverSkillPayload",
    "send_mattermost",
    "send_notify",
    "send_pushover",
    "ObsidianSkillError",
    "notes_search",
    "obsidian_skill_handlers",
    "tasks_create",
    "UniFiSkillError",
    "clients",
    "health_check",
    "unifi_skill_handlers",
    "wan_status",
]
