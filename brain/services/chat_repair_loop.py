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
from brain.services.chat_output_contract import (
    ChatOutputContract,
    ChatOutputContractEvaluation,
    ChatOutputContractFeasibility,
    apply_chat_output_contract_verification,
    evaluate_chat_output_contract,
    evaluate_chat_output_contract_feasibility,
    normalize_chat_output_contract_response,
    render_chat_output_contract_repair_prompt,
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
    output_contract: ChatOutputContractEvaluation | None = None
    output_contract_feasibility: ChatOutputContractFeasibility | None = None

    def to_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
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
        if self.output_contract is not None:
            metadata.update(self.output_contract.to_metadata())
        if self.output_contract_feasibility is not None:
            metadata.update(self.output_contract_feasibility.to_metadata())
        return metadata


async def run_chat_repair_loop(
    *,
    response_text: str,
    user_msg: str,
    evidence_pack: ChatEvidencePack,
    verification: ChatResponseVerification | None = None,
    retry_once: Callable[[str], Awaitable[ChatRepairAttemptResult]] | None = None,
    output_contract: ChatOutputContract | None = None,
) -> ChatRepairLoopResult:
    """Run one repair pass only when the failure is bounded and auditable."""

    verification = verification or verify_chat_response(
        response_text=response_text,
        evidence_pack=evidence_pack,
    )
    if output_contract is not None:
        feasibility = evaluate_chat_output_contract_feasibility(output_contract)
        if not feasibility.feasible:
            evaluation = ChatOutputContractEvaluation(
                contract_id=output_contract.contract_id,
                passed=False,
                issues=("contract_infeasible",),
            )
            failed_verification = apply_chat_output_contract_verification(
                verification,
                evaluation,
            )
            return ChatRepairLoopResult(
                text=response_text,
                verification=failed_verification,
                attempted=False,
                repaired=False,
                attempts=0,
                action="skip_generation",
                reason="output_contract_infeasible",
                before_issues=failed_verification.issues,
                after_issues=failed_verification.issues,
                output_contract=evaluation,
                output_contract_feasibility=feasibility,
            )
        return await _run_output_contract_repair(
            response_text=response_text,
            user_msg=user_msg,
            evidence_pack=evidence_pack,
            verification=verification,
            retry_once=retry_once,
            output_contract=output_contract,
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


async def _run_output_contract_repair(
    *,
    response_text: str,
    user_msg: str,
    evidence_pack: ChatEvidencePack,
    verification: ChatResponseVerification,
    retry_once: Callable[[str], Awaitable[ChatRepairAttemptResult]] | None,
    output_contract: ChatOutputContract,
) -> ChatRepairLoopResult:
    initial_evaluation = evaluate_chat_output_contract(response_text, output_contract)
    initial_verification = apply_chat_output_contract_verification(
        verification,
        initial_evaluation,
    )
    normalized_text, normalized = normalize_chat_output_contract_response(
        response_text,
        output_contract,
    )
    evaluation = evaluate_chat_output_contract(normalized_text, output_contract)
    combined_verification = apply_chat_output_contract_verification(
        verification,
        evaluation,
    )
    if combined_verification.verified and not (
        combined_verification.requires_web_verification
    ):
        if normalized:
            return ChatRepairLoopResult(
                text=normalized_text,
                verification=combined_verification,
                attempted=True,
                repaired=True,
                attempts=1,
                action="normalize_output_contract",
                reason="output_contract_normalized",
                before_issues=initial_verification.issues,
                after_issues=combined_verification.issues,
                output_contract=evaluation,
            )
        return _no_repair(
            normalized_text,
            combined_verification,
            "already_verified",
            output_contract=evaluation,
        )
    if combined_verification.requires_web_verification or (
        "unsupported_web_verification_claim" in combined_verification.issues
    ):
        return _no_repair(
            response_text,
            combined_verification,
            "requires_beacon",
            output_contract=evaluation,
        )
    if not retry_once:
        return _no_repair(
            response_text,
            combined_verification,
            "issue_not_repairable",
            output_contract=evaluation,
        )

    repair_context = render_chat_evidence_prompt(
        evidence_pack=evidence_pack,
        user_msg=user_msg,
        response_style_context=(
            "Repair loop: answer from the provided evidence and original request. "
            "Do not claim web access unless Beacon evidence is present."
        ),
    )
    repair_prompt = render_chat_output_contract_repair_prompt(
        user_msg=repair_context,
        contract=output_contract,
        issues=evaluation.issues,
    )
    retry = await retry_once(repair_prompt)
    retry_text, _retry_normalized = normalize_chat_output_contract_response(
        retry.text,
        output_contract,
    )
    retry_verification = verify_chat_response(
        response_text=retry_text,
        evidence_pack=evidence_pack,
    )
    retry_evaluation = evaluate_chat_output_contract(retry_text, output_contract)
    repaired_verification = apply_chat_output_contract_verification(
        retry_verification,
        retry_evaluation,
    )
    if repaired_verification.verified and not (
        repaired_verification.requires_web_verification
    ):
        return ChatRepairLoopResult(
            text=retry_text,
            verification=repaired_verification,
            attempted=True,
            repaired=True,
            attempts=1,
            action="retry_local_once",
            reason="output_contract_repaired",
            before_issues=combined_verification.issues,
            after_issues=repaired_verification.issues,
            model_used=retry.model_used,
            output_contract=retry_evaluation,
        )
    return ChatRepairLoopResult(
        text=response_text,
        verification=combined_verification,
        attempted=True,
        repaired=False,
        attempts=1,
        action="retry_local_once",
        reason="output_contract_retry_failed_verification",
        before_issues=combined_verification.issues,
        after_issues=repaired_verification.issues,
        model_used=retry.model_used,
        output_contract=retry_evaluation,
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
    *,
    output_contract: ChatOutputContractEvaluation | None = None,
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
        output_contract=output_contract,
    )
