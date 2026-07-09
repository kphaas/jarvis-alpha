"""Bounded repair loop for Alpha chat responses."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from brain.services.chat_evidence_pack import (
    ChatEvidencePack,
    ChatResponseVerification,
    UNSUPPORTED_WEB_PROOF_RE,
    render_chat_evidence_prompt,
    verify_chat_response,
)

CHAT_REPAIR_LOOP_SCHEMA_VERSION = "chat_repair_loop.v1"
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class ChatRepairAttemptResult:
    text: str
    model_used: str | None = None


@dataclass(frozen=True)
class ChatRepairLoopResult:
    text: str
    verification: ChatResponseVerification
    attempted: bool
    repaired: bool
    attempts: int
    action: str
    reason: str
    before_issues: tuple[str, ...]
    after_issues: tuple[str, ...]
    model_used: str | None = None

    def to_metadata(self) -> dict[str, object]:
        return {
            "chat_repair_loop_schema_version": CHAT_REPAIR_LOOP_SCHEMA_VERSION,
            "chat_repair_attempted": self.attempted,
            "chat_repair_repaired": self.repaired,
            "chat_repair_attempt_count": self.attempts,
            "chat_repair_action": self.action,
            "chat_repair_reason": self.reason,
            "chat_repair_before_issues": list(self.before_issues),
            "chat_repair_after_issues": list(self.after_issues),
            "chat_repair_model_used": self.model_used,
        }


async def run_chat_repair_loop(
    *,
    response_text: str,
    user_msg: str,
    evidence_pack: ChatEvidencePack,
    verification: ChatResponseVerification | None = None,
    retry_once: Callable[[str], Awaitable[ChatRepairAttemptResult]] | None = None,
) -> ChatRepairLoopResult:
    """Run one repair pass only when the failure is bounded and auditable."""

    verification = verification or verify_chat_response(
        response_text=response_text,
        evidence_pack=evidence_pack,
    )
    deterministic = repair_chat_response_once(
        response_text=response_text,
        evidence_pack=evidence_pack,
        verification=verification,
    )
    if (
        deterministic.attempted
        or deterministic.reason != "issue_not_repairable"
        or "empty_response" not in verification.issues
    ):
        return deterministic

    if not retry_once:
        return _no_repair(response_text, verification, "issue_not_repairable")

    repair_prompt = _empty_response_repair_prompt(
        user_msg=user_msg,
        evidence_pack=evidence_pack,
    )
    retry = await retry_once(repair_prompt)
    repaired_verification = verify_chat_response(
        response_text=retry.text,
        evidence_pack=evidence_pack,
    )
    if repaired_verification.verified and not (
        repaired_verification.requires_web_verification
    ):
        return ChatRepairLoopResult(
            text=retry.text,
            verification=repaired_verification,
            attempted=True,
            repaired=True,
            attempts=1,
            action="retry_local_once",
            reason="empty_response_repaired",
            before_issues=verification.issues,
            after_issues=repaired_verification.issues,
            model_used=retry.model_used,
        )
    return ChatRepairLoopResult(
        text=response_text,
        verification=verification,
        attempted=True,
        repaired=False,
        attempts=1,
        action="retry_local_once",
        reason="empty_response_retry_failed_verification",
        before_issues=verification.issues,
        after_issues=repaired_verification.issues,
        model_used=retry.model_used,
    )


def repair_chat_response_once(
    *,
    response_text: str,
    evidence_pack: ChatEvidencePack,
    verification: ChatResponseVerification | None = None,
) -> ChatRepairLoopResult:
    """Run deterministic repair only; never calls a model."""

    verification = verification or verify_chat_response(
        response_text=response_text,
        evidence_pack=evidence_pack,
    )
    if verification.verified and not verification.requires_web_verification:
        return _no_repair(response_text, verification, "already_verified")
    if verification.requires_web_verification:
        return _no_repair(response_text, verification, "requires_beacon")
    if evidence_pack.evidence_count == 0:
        return _no_repair(response_text, verification, "no_evidence_for_repair")

    if "unsupported_web_verification_claim" in verification.issues:
        return _repair_unsupported_web_claim(
            response_text=response_text,
            evidence_pack=evidence_pack,
            verification=verification,
        )

    return _no_repair(response_text, verification, "issue_not_repairable")


def _repair_unsupported_web_claim(
    *,
    response_text: str,
    evidence_pack: ChatEvidencePack,
    verification: ChatResponseVerification,
) -> ChatRepairLoopResult:
    repaired_text = _strip_unsupported_web_claim_sentences(response_text)
    if not repaired_text or repaired_text == response_text.strip():
        return ChatRepairLoopResult(
            text=response_text,
            verification=verification,
            attempted=True,
            repaired=False,
            attempts=1,
            action="strip_unsupported_web_claim",
            reason="unsupported_web_claim_not_isolated",
            before_issues=verification.issues,
            after_issues=verification.issues,
        )

    repaired_verification = verify_chat_response(
        response_text=repaired_text,
        evidence_pack=evidence_pack,
    )
    if (
        repaired_verification.verified
        and not repaired_verification.requires_web_verification
    ):
        return ChatRepairLoopResult(
            text=repaired_text,
            verification=repaired_verification,
            attempted=True,
            repaired=True,
            attempts=1,
            action="strip_unsupported_web_claim",
            reason="unsupported_web_claim_repaired",
            before_issues=verification.issues,
            after_issues=repaired_verification.issues,
        )

    return ChatRepairLoopResult(
        text=response_text,
        verification=verification,
        attempted=True,
        repaired=False,
        attempts=1,
        action="strip_unsupported_web_claim",
        reason="repaired_text_failed_verification",
        before_issues=verification.issues,
        after_issues=repaired_verification.issues,
    )


def _strip_unsupported_web_claim_sentences(text: str) -> str:
    parts = _SENTENCE_BOUNDARY_RE.split(text.strip())
    kept = [part for part in parts if not UNSUPPORTED_WEB_PROOF_RE.search(part)]
    return " ".join(part.strip() for part in kept if part.strip())


def _empty_response_repair_prompt(
    *,
    user_msg: str,
    evidence_pack: ChatEvidencePack,
) -> str:
    return render_chat_evidence_prompt(
        evidence_pack=evidence_pack,
        user_msg=user_msg,
        response_style_context=(
            "Repair loop: the previous model returned an empty answer. "
            "Answer concisely using only the provided evidence. If the evidence "
            "is insufficient, say that without claiming web access."
        ),
    )


def _no_repair(
    response_text: str,
    verification: ChatResponseVerification,
    reason: str,
) -> ChatRepairLoopResult:
    return ChatRepairLoopResult(
        text=response_text,
        verification=verification,
        attempted=False,
        repaired=False,
        attempts=0,
        action="none",
        reason=reason,
        before_issues=verification.issues,
        after_issues=verification.issues,
    )
