"""Prompt evidence packing for Alpha chat."""

from __future__ import annotations

from dataclasses import dataclass


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
