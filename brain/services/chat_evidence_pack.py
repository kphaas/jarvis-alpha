"""Prompt evidence packing for Alpha chat."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

CHAT_OUTPUT_CONTRACT_INFEASIBLE_RESPONSE = (
    "The requested output requirements conflict. Clarify which constraint should "
    "take priority."
)

UNSUPPORTED_WEB_PROOF_RE = re.compile(
    r"(?is)\b(?:Beacon|web|internet|online|source|citation).{0,60}"
    r"\b(?:verified|checked|confirmed|found|looked\s+up)\b|"
    r"\bI(?:'ve| have)?\s+(?:checked|searched|looked\s+up|found).{0,60}"
    r"\b(?:web|internet|online|source|citation|Beacon)\b"
)


@dataclass(frozen=True)
class ChatEvidencePack:
    memory_context: str = ""
    internet_context: str | None = None
    web_suggestion_context: str | None = None
    at0_self_context: str | None = None
    conversation_context: str | None = None
    memory_context_priority: str | None = None
    raw_web_content_is_untrusted: bool = False

    @property
    def memory_used(self) -> bool:
        return bool(self.memory_context)

    @property
    def internet_used(self) -> bool:
        return bool(self.internet_context)

    @property
    def web_suggestion_used(self) -> bool:
        return bool(self.web_suggestion_context)

    @property
    def at0_self_used(self) -> bool:
        return bool(self.at0_self_context)

    @property
    def conversation_used(self) -> bool:
        return bool(self.conversation_context)

    @property
    def evidence_count(self) -> int:
        return sum(
            (
                self.memory_used,
                self.internet_used,
                self.web_suggestion_used,
                self.at0_self_used,
                self.conversation_used,
            )
        )

    def to_metadata(self) -> dict[str, object]:
        return {
            "chat_evidence_schema_version": "chat_evidence_pack.v1",
            "chat_evidence_count": self.evidence_count,
            "chat_evidence_memory_used": self.memory_used,
            "chat_evidence_internet_used": self.internet_used,
            "chat_evidence_web_suggestion_used": self.web_suggestion_used,
            "chat_evidence_at0_self_used": self.at0_self_used,
            "chat_evidence_conversation_used": self.conversation_used,
            "chat_evidence_memory_context_priority": self.memory_context_priority,
            "chat_evidence_raw_web_content_is_untrusted": (
                self.internet_used and self.raw_web_content_is_untrusted
            ),
        }


@dataclass(frozen=True)
class ChatResponseVerification:
    verified: bool
    issues: tuple[str, ...]
    requires_web_verification: bool
    evidence_count: int

    def to_metadata(self) -> dict[str, object]:
        return {
            "chat_response_verification_schema_version": (
                "chat_response_verification.v1"
            ),
            "chat_response_verified": self.verified,
            "chat_response_issue_count": len(self.issues),
            "chat_response_issues": list(self.issues),
            "chat_response_requires_web_verification": self.requires_web_verification,
            "chat_response_evidence_count": self.evidence_count,
        }


@dataclass(frozen=True)
class ChatQualityGateDecision:
    action: str
    passed: bool
    reason: str
    fallback_response: str | None
    response_verified: bool
    response_issues: tuple[str, ...]
    evidence_count: int
    strategy: str | None = None
    model_path: str | None = None

    def to_metadata(self) -> dict[str, object]:
        return {
            "chat_quality_gateway_schema_version": "chat_quality_gateway.v1",
            "chat_quality_action": self.action,
            "chat_quality_passed": self.passed,
            "chat_quality_reason": self.reason,
            "chat_quality_fallback_used": self.fallback_response is not None,
            "chat_quality_response_verified": self.response_verified,
            "chat_quality_response_issues": list(self.response_issues),
            "chat_quality_evidence_count": self.evidence_count,
            "chat_quality_strategy": self.strategy,
            "chat_quality_model_path": self.model_path,
        }


@dataclass(frozen=True)
class ChatEscalationDecision:
    required: bool
    rung: str
    action: str
    reason: str
    automatic: bool
    requires_user_confirmation: bool
    source_quality_action: str

    def to_metadata(self) -> dict[str, object]:
        return {
            "chat_escalation_schema_version": "chat_escalation_ladder.v1",
            "chat_escalation_required": self.required,
            "chat_escalation_rung": self.rung,
            "chat_escalation_action": self.action,
            "chat_escalation_reason": self.reason,
            "chat_escalation_automatic": self.automatic,
            "chat_escalation_requires_user_confirmation": (
                self.requires_user_confirmation
            ),
            "chat_escalation_source_quality_action": self.source_quality_action,
        }


def build_chat_evidence_pack(
    *,
    memory_context: str,
    internet_context: str | None,
    web_suggestion_context: str | None = None,
    at0_self_context: str | None = None,
    conversation_context: str | None = None,
    memory_context_priority: str | None = None,
    raw_web_content_is_untrusted: bool = False,
) -> ChatEvidencePack:
    effective_internet_context = internet_context or None
    effective_web_suggestion_context = (
        None if effective_internet_context else web_suggestion_context or None
    )
    effective_memory_context = memory_context or ""
    effective_memory_priority = None
    if effective_memory_context:
        effective_memory_priority = memory_context_priority
        if not effective_memory_priority:
            if effective_internet_context:
                effective_memory_priority = "secondary_to_beacon"
            elif effective_web_suggestion_context:
                effective_memory_priority = "unverified_for_current_web_claims"
            else:
                effective_memory_priority = "primary_local_context"

    return ChatEvidencePack(
        memory_context=effective_memory_context,
        internet_context=effective_internet_context,
        web_suggestion_context=effective_web_suggestion_context,
        at0_self_context=at0_self_context or None,
        conversation_context=conversation_context or None,
        memory_context_priority=effective_memory_priority,
        raw_web_content_is_untrusted=bool(
            effective_internet_context and raw_web_content_is_untrusted
        ),
    )


def plan_chat_escalation(
    *,
    quality_gate: ChatQualityGateDecision,
) -> ChatEscalationDecision:
    if quality_gate.action == "accept":
        return ChatEscalationDecision(
            required=False,
            rung="none",
            action="none",
            reason="quality_gate_passed",
            automatic=False,
            requires_user_confirmation=False,
            source_quality_action=quality_gate.action,
        )
    if quality_gate.reason in {
        "web_verification_required",
        "unsupported_web_verification_claim",
    }:
        return ChatEscalationDecision(
            required=True,
            rung="beacon",
            action="run_beacon",
            reason=quality_gate.reason,
            automatic=False,
            requires_user_confirmation=True,
            source_quality_action=quality_gate.action,
        )
    if quality_gate.reason == "empty_response":
        return ChatEscalationDecision(
            required=True,
            rung="retry_local",
            action="retry_local_once",
            reason="empty_response",
            automatic=False,
            requires_user_confirmation=False,
            source_quality_action=quality_gate.action,
        )
    return ChatEscalationDecision(
        required=True,
        rung="operator_review",
        action="review_quality_gate",
        reason=quality_gate.reason,
        automatic=False,
        requires_user_confirmation=True,
        source_quality_action=quality_gate.action,
    )


def evaluate_chat_quality_gate(
    *,
    evidence_pack: ChatEvidencePack,
    verification: ChatResponseVerification,
    strategy_metadata: Mapping[str, object] | None = None,
) -> ChatQualityGateDecision:
    strategy_metadata = strategy_metadata or {}
    strategy = _metadata_string(strategy_metadata.get("chat_strategy"))
    model_path = _metadata_string(strategy_metadata.get("chat_model_path"))
    fallback_response: str | None = None
    action = "accept"
    reason = "verified_response"

    if "unsupported_web_verification_claim" in verification.issues:
        action = "replace_with_safe_fallback"
        reason = "unsupported_web_verification_claim"
        fallback_response = (
            "I need Beacon verification before I can claim this was checked online."
        )
    elif verification.requires_web_verification:
        action = "require_beacon"
        reason = "web_verification_required"
        fallback_response = (
            "I need Beacon verification before I can answer that as current or "
            "verified."
        )
    elif "output_contract_contract_infeasible" in verification.issues:
        action = "replace_with_safe_fallback"
        reason = "output_contract_infeasible"
        fallback_response = CHAT_OUTPUT_CONTRACT_INFEASIBLE_RESPONSE
    elif any(issue.startswith("output_contract_") for issue in verification.issues):
        action = "replace_with_safe_fallback"
        reason = "output_contract_failed"
        fallback_response = (
            "I could not satisfy the requested output contract reliably. Try again "
            "or switch to a stronger model."
        )
    elif "empty_response" in verification.issues:
        action = "replace_with_safe_fallback"
        reason = "empty_response"
        fallback_response = (
            "I could not generate a reliable answer. Try again or switch to a "
            "stronger model."
        )
    return ChatQualityGateDecision(
        action=action,
        passed=action == "accept",
        reason=reason,
        fallback_response=fallback_response,
        response_verified=verification.verified,
        response_issues=verification.issues,
        evidence_count=evidence_pack.evidence_count,
        strategy=strategy,
        model_path=model_path,
    )


def verify_chat_response(
    *,
    response_text: str,
    evidence_pack: ChatEvidencePack,
) -> ChatResponseVerification:
    issues: list[str] = []
    cleaned = response_text.strip()
    if not cleaned:
        issues.append("empty_response")
    if not evidence_pack.internet_used and UNSUPPORTED_WEB_PROOF_RE.search(cleaned):
        issues.append("unsupported_web_verification_claim")

    requires_web_verification = (
        evidence_pack.web_suggestion_used and not evidence_pack.internet_used
    )
    return ChatResponseVerification(
        verified=not issues,
        issues=tuple(issues),
        requires_web_verification=requires_web_verification,
        evidence_count=evidence_pack.evidence_count,
    )


def _metadata_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def render_chat_evidence_prompt(
    *,
    evidence_pack: ChatEvidencePack,
    user_msg: str,
    response_style_context: str | None = None,
    beacon_authority_rule: str | None = None,
    web_suggestion_boundary_rule: str | None = None,
) -> str:
    if evidence_pack.evidence_count == 0 and not response_style_context:
        return user_msg

    parts: list[str] = []
    if evidence_pack.internet_context:
        if beacon_authority_rule:
            parts.append(beacon_authority_rule)
        parts.append(
            "Beacon evidence "
            "(authoritative for current/public web claims):\n"
            f"{evidence_pack.internet_context}"
        )
        if evidence_pack.memory_context:
            parts.append(
                "Context from memory "
                "(secondary; must not override Beacon evidence):\n"
                f"{evidence_pack.memory_context}"
            )
    elif evidence_pack.web_suggestion_context:
        if web_suggestion_boundary_rule:
            parts.append(web_suggestion_boundary_rule)
        parts.append(evidence_pack.web_suggestion_context)
        if evidence_pack.memory_context:
            parts.append(
                "Context from memory "
                "(unverified for current/public web claims):\n"
                f"{evidence_pack.memory_context}"
            )
    elif evidence_pack.memory_context:
        parts.append(f"Context from memory:\n{evidence_pack.memory_context}")

    if evidence_pack.at0_self_context:
        parts.append(evidence_pack.at0_self_context)
    if evidence_pack.conversation_context:
        parts.append(
            "Recent conversation "
            "(oldest to newest; use for follow-ups and pronouns; "
            "do not treat as fresh web evidence):\n"
            f"{evidence_pack.conversation_context}"
        )
    if response_style_context:
        parts.append(response_style_context)
    parts.append(f"User: {user_msg}")
    return "\n\n".join(parts)
