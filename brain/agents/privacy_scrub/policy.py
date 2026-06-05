"""Approval-tier policy for privacy-scrub actions.

The privacy-scrub agent sends or searches for personal data, including minor
data and court-record material. This module stays intentionally conservative:
anything that is external, legal, minor-related, or identity-document backed is
blocked for human approval before execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from brain.agents.privacy_scrub.subjects import Subject
from brain.agents.privacy_scrub.targets import OptOutMethod, Target

ApprovalTier = Literal["T1", "T2", "T3", "T4", "T5"]


class ActionType(str, Enum):
    SCAN_LOCAL = "scan_local"
    SCAN_EXTERNAL = "scan_external"
    DRAFT = "draft"
    SEND_OPT_OUT = "send_opt_out"
    FILE_MOTION = "file_motion"
    VERIFY = "verify"


@dataclass(frozen=True, slots=True)
class TierDecision:
    tier: ApprovalTier
    reason: str
    method_override: OptOutMethod | None = None


def evaluate_tier(
    subject: Subject,
    action: ActionType,
    target: Target,
) -> TierDecision:
    """Map a privacy action to an Alpha approval tier."""
    if action == ActionType.FILE_MOTION:
        return TierDecision(
            tier="T5",
            reason="Court filings are legal actions and require PIN re-entry.",
        )

    if subject.is_minor and action in (
        ActionType.SEND_OPT_OUT,
        ActionType.SCAN_EXTERNAL,
        ActionType.VERIFY,
    ):
        return TierDecision(
            tier="T5",
            reason=(
                f"{subject.display_name} is a minor; external privacy actions "
                "require guardian PIN re-entry."
            ),
            method_override=OptOutMethod.MANUAL_ONLY,
        )

    if action == ActionType.SEND_OPT_OUT and (
        target.requires_identity_document
        or target.requires_sensitive_payload
        or target.opt_out_method == OptOutMethod.MANUAL_ONLY
    ):
        return TierDecision(
            tier="T5",
            reason=(
                f"Target {target.id!r} requires sensitive identity material; "
                "PIN re-entry is required."
            ),
            method_override=OptOutMethod.MANUAL_ONLY,
        )

    if action == ActionType.SEND_OPT_OUT:
        return TierDecision(
            tier="T4",
            reason="External opt-out send requires human approval.",
        )

    if action == ActionType.SCAN_EXTERNAL:
        return TierDecision(
            tier="T4",
            reason="External scan may disclose identifiers to a third party.",
        )

    if action == ActionType.VERIFY:
        return TierDecision(
            tier="T4",
            reason="External verification discloses lookup data to a third party.",
        )

    if (
        action == ActionType.DRAFT
        and target.opt_out_method == OptOutMethod.COURT_MOTION
    ):
        return TierDecision(
            tier="T4",
            reason="Court-motion drafts require human legal review.",
        )

    if action == ActionType.DRAFT:
        return TierDecision(
            tier="T2",
            reason="Local draft generation has no external side effects.",
        )

    if action == ActionType.SCAN_LOCAL:
        return TierDecision(
            tier="T1",
            reason="Local inventory action has no external side effects.",
        )

    raise ValueError(
        f"evaluate_tier: unhandled combination "
        f"(role={subject.role.value!r}, action={action.value!r})"
    )
