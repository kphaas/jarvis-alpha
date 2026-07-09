"""Deterministic prompt compiler for Alpha chat."""

from __future__ import annotations

from dataclasses import dataclass

from brain.services.chat_evidence_pack import (
    ChatEvidencePack,
    build_chat_evidence_pack,
    render_chat_evidence_prompt,
)

PROMPT_MANIFEST_SCHEMA_VERSION = "chat_prompt_manifest.v1"


@dataclass(frozen=True)
class ChatPromptManifest:
    section_order: tuple[str, ...]
    user_message_chars: int
    compiled_prompt_chars: int
    memory_used: bool
    internet_used: bool
    web_suggestion_used: bool
    at0_self_used: bool
    conversation_used: bool
    raw_web_content_is_untrusted: bool
    memory_context_priority: str | None
    response_style_used: bool
    tool_policy: str

    def to_metadata(self) -> dict[str, object]:
        return {
            "chat_prompt_schema_version": PROMPT_MANIFEST_SCHEMA_VERSION,
            "chat_prompt_section_order": list(self.section_order),
            "chat_prompt_user_message_chars": self.user_message_chars,
            "chat_prompt_compiled_chars": self.compiled_prompt_chars,
            "chat_prompt_memory_used": self.memory_used,
            "chat_prompt_internet_used": self.internet_used,
            "chat_prompt_web_suggestion_used": self.web_suggestion_used,
            "chat_prompt_at0_self_used": self.at0_self_used,
            "chat_prompt_conversation_used": self.conversation_used,
            "chat_prompt_raw_web_content_is_untrusted": (
                self.raw_web_content_is_untrusted
            ),
            "chat_prompt_memory_context_priority": self.memory_context_priority,
            "chat_prompt_response_style_used": self.response_style_used,
            "chat_prompt_tool_policy": self.tool_policy,
        }


@dataclass(frozen=True)
class CompiledChatPrompt:
    prompt: str
    evidence_pack: ChatEvidencePack
    manifest: ChatPromptManifest


def compile_chat_prompt(
    *,
    user_msg: str,
    memory_context: str,
    internet_context: str | None,
    web_suggestion_context: str | None = None,
    at0_self_context: str | None = None,
    conversation_context: str | None = None,
    response_style_context: str | None = None,
    memory_context_priority: str | None = None,
    raw_web_content_is_untrusted: bool = False,
    beacon_authority_rule: str | None = None,
    web_suggestion_boundary_rule: str | None = None,
) -> CompiledChatPrompt:
    evidence_pack = build_chat_evidence_pack(
        memory_context=memory_context,
        internet_context=internet_context,
        web_suggestion_context=web_suggestion_context,
        at0_self_context=at0_self_context,
        conversation_context=conversation_context,
        memory_context_priority=memory_context_priority,
        raw_web_content_is_untrusted=raw_web_content_is_untrusted,
    )
    prompt = render_chat_evidence_prompt(
        evidence_pack=evidence_pack,
        user_msg=user_msg,
        response_style_context=response_style_context,
        beacon_authority_rule=beacon_authority_rule,
        web_suggestion_boundary_rule=web_suggestion_boundary_rule,
    )
    return CompiledChatPrompt(
        prompt=prompt,
        evidence_pack=evidence_pack,
        manifest=ChatPromptManifest(
            section_order=_section_order(
                evidence_pack=evidence_pack,
                response_style_context=response_style_context,
                beacon_authority_rule=beacon_authority_rule,
                web_suggestion_boundary_rule=web_suggestion_boundary_rule,
            ),
            user_message_chars=len(user_msg),
            compiled_prompt_chars=len(prompt),
            memory_used=evidence_pack.memory_used,
            internet_used=evidence_pack.internet_used,
            web_suggestion_used=evidence_pack.web_suggestion_used,
            at0_self_used=evidence_pack.at0_self_used,
            conversation_used=evidence_pack.conversation_used,
            raw_web_content_is_untrusted=(
                evidence_pack.internet_used
                and evidence_pack.raw_web_content_is_untrusted
            ),
            memory_context_priority=evidence_pack.memory_context_priority,
            response_style_used=bool(response_style_context),
            tool_policy=_tool_policy(evidence_pack),
        ),
    )


def _section_order(
    *,
    evidence_pack: ChatEvidencePack,
    response_style_context: str | None,
    beacon_authority_rule: str | None,
    web_suggestion_boundary_rule: str | None,
) -> tuple[str, ...]:
    sections: list[str] = []
    if evidence_pack.internet_used:
        if beacon_authority_rule:
            sections.append("beacon_authority_rule")
        sections.append("beacon_evidence")
        if evidence_pack.memory_used:
            sections.append("memory_secondary_to_beacon")
    elif evidence_pack.web_suggestion_used:
        if web_suggestion_boundary_rule:
            sections.append("web_suggestion_boundary")
        sections.append("web_suggestion")
        if evidence_pack.memory_used:
            sections.append("memory_unverified_for_web_claims")
    elif evidence_pack.memory_used:
        sections.append("memory")

    if evidence_pack.at0_self_used:
        sections.append("at0_self")
    if evidence_pack.conversation_used:
        sections.append("conversation")
    if response_style_context:
        sections.append("response_style")
    sections.append("user_message")
    return tuple(sections)


def _tool_policy(evidence_pack: ChatEvidencePack) -> str:
    if evidence_pack.internet_used:
        return "beacon_evidence_is_authority"
    if evidence_pack.web_suggestion_used:
        return "web_suggestion_requires_confirmation"
    return "no_external_tool_executed"
