"""Spark iMessage draft proposal service.

This service may read an approved one-to-one iMessage thread at runtime, but it
does not persist raw message bodies or expose them in the response payload.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol

from brain.core.models import CLAUDE_FAST
from brain.config.secrets import get_secret
from brain.services.llm_transport import call_gateway_cloud
from brain.services.auto_brain import (
    AutoBrainConfigError,
    AutoSparkPromptContext,
    load_auto_spark_prompt_context,
)
from brain.services.bluebubbles_client import (
    BlueBubblesClientError,
    BlueBubblesConfigError,
    BlueBubblesMessageBody,
    BlueBubblesPolicyError,
    BlueBubblesReadOnlyClient,
)
from brain.services.spark_corpus_ingest import (
    SparkCorpusApproval,
    plan_approved_corpus_ingest,
)
from brain.services.spark_voice_ingest import (
    SparkApprovedSourceRecord,
    SparkVoiceGuidance,
    load_approved_voice_sources,
    load_spark_voice_guidance,
)
from brain.services.spark_persona_guardrails import load_spark_guardrails
from brain.services.spark_sensitivity import scan_spark_draft_sensitivity

DRAFT_VERSION = "spark-imessage-draft/v0.2"
DEFAULT_MAX_CONTEXT_MESSAGES = 20
PERSONALITY_MEMORY_MAX_PROMPT_LINES = 18
PERSONALITY_MEMORY_DRAFT_KINDS = frozenset(
    {
        "voice",
        "avoid",
        "phrase",
        "relationship",
        "value",
        "style",
        "preference",
    }
)
PERSONALITY_MEMORY_BLOCKED = re.compile(
    r"\b(password|token|secret|private key|raw thread|message body|phone number)\b",
    re.IGNORECASE,
)
RELATIONSHIP_MEMORY = re.compile(
    r"^(?P<label>[^:]{1,80}):\s*(?P<relationship>[^;]{1,80})(?:;.*)?$"
)
MAX_CONTEXT_MESSAGES = 50
APPROVED_CHAT_GUID_ENV = "SPARK_IMESSAGE_APPROVED_CHAT_GUID"
SPARK_DRAFT_LLM_PROVIDER_ENV = "SPARK_DRAFT_LLM_PROVIDER"
SPARK_DRAFT_LLM_MODEL_ENV = "SPARK_DRAFT_LLM_MODEL"
SPARK_DRAFT_LLM_ENABLED_ENV = "SPARK_DRAFT_LLM_ENABLED"
SPARK_DRAFT_LLM_REQUIRED_ENV = "SPARK_DRAFT_LLM_REQUIRED"
SPARK_DRAFT_LLM_TIMEOUT_ENV = "SPARK_DRAFT_LLM_TIMEOUT_SEC"
SparkLLMCall = Callable[..., Awaitable[str]]


class SparkDraftPolicyError(RuntimeError):
    """Raised when Spark policy does not allow an iMessage draft context."""


class SparkDraftConfigError(RuntimeError):
    """Raised when runtime-only Spark draft config is missing."""


class SparkDraftContextError(RuntimeError):
    """Raised when approved iMessage context cannot be loaded."""


class SparkIMessageBodyClient(Protocol):
    async def approved_messages_for_chat(
        self,
        *,
        chat_guid: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[BlueBubblesMessageBody, ...]: ...


@dataclass(frozen=True, slots=True)
class SparkRuntimeMessage:
    message_ref_hash: str
    is_from_me: bool
    body_text: str


@dataclass(frozen=True, slots=True)
class SparkDraftConversationSummary:
    channel: str
    voice_principal_label: str
    reply_target_label: str
    reply_target_confidence: str
    context_order: str = "newest_first"


@dataclass(frozen=True, slots=True)
class SparkDraftQualityCheck:
    key: str
    label: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class SparkDraftQualityScorecard:
    score: int
    verdict: str
    checks: tuple[SparkDraftQualityCheck, ...]


@dataclass(frozen=True, slots=True)
class SparkDraftSourceReadiness:
    source: str
    channel: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class SparkPersonalityMemoryPromptItem:
    kind: str
    content: str
    source: str
    evidence_ref_hash: str | None = None


@dataclass(frozen=True, slots=True)
class SparkDraftContext:
    principal_id: str
    approval_ref_hash: str
    source_reference_hash: str
    chat_guid_hash: str
    messages: tuple[SparkRuntimeMessage, ...]
    body_access: bool = True
    durable_storage_allowed: bool = False

    @property
    def principal_sent_messages(self) -> int:
        return sum(1 for message in self.messages if message.is_from_me)

    @property
    def runtime_context_messages(self) -> int:
        return sum(1 for message in self.messages if not message.is_from_me)


@dataclass(frozen=True, slots=True)
class SparkDraftProposal:
    principal_id: str
    draft_text: str
    context: SparkDraftContext
    warnings: tuple[str, ...]
    conversation_summary: SparkDraftConversationSummary
    draft_quality: SparkDraftQualityScorecard
    source_readiness: tuple[SparkDraftSourceReadiness, ...]
    detected_sensitivity: tuple[str, ...] = ()
    blocked_sensitivity: tuple[str, ...] = ()
    draft_engine: str = "deterministic_v0"
    draft_version: str = DRAFT_VERSION
    can_send: bool = False
    requires_human_approval: bool = True

    def to_payload(
        self,
        *,
        include_context_preview: bool = False,
        context_preview_limit: int = 10,
        personality_memory_preview: list[dict[str, object]] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "draft_version": self.draft_version,
            "principal_id": self.principal_id,
            "draft_text": self.draft_text,
            "can_send": self.can_send,
            "requires_human_approval": self.requires_human_approval,
            "body_access": self.context.body_access,
            "durable_storage_allowed": self.context.durable_storage_allowed,
            "context_messages_read": len(self.context.messages),
            "principal_sent_messages": self.context.principal_sent_messages,
            "runtime_context_messages": self.context.runtime_context_messages,
            "approval_ref_hash": self.context.approval_ref_hash,
            "source_reference_hash": self.context.source_reference_hash,
            "chat_guid_hash": self.context.chat_guid_hash,
            "warnings": list(self.warnings),
            "detected_sensitivity": list(self.detected_sensitivity),
            "blocked_sensitivity": list(self.blocked_sensitivity),
            "draft_engine": self.draft_engine,
            "conversation_summary": {
                "channel": self.conversation_summary.channel,
                "voice_principal_label": self.conversation_summary.voice_principal_label,
                "reply_target_label": self.conversation_summary.reply_target_label,
                "reply_target_confidence": self.conversation_summary.reply_target_confidence,
                "context_order": self.conversation_summary.context_order,
                "last_message_speaker": None,
                "last_message_preview": None,
                "last_message_ref_hash": None,
            },
            "draft_quality": {
                "score": self.draft_quality.score,
                "verdict": self.draft_quality.verdict,
                "checks": [
                    {
                        "key": check.key,
                        "label": check.label,
                        "passed": check.passed,
                        "detail": check.detail,
                    }
                    for check in self.draft_quality.checks
                ],
            },
            "source_readiness": [
                {
                    "source": item.source,
                    "channel": item.channel,
                    "status": item.status,
                    "detail": item.detail,
                }
                for item in self.source_readiness
            ],
            "context_preview": [],
            "personality_memory_preview": personality_memory_preview or [],
        }
        if include_context_preview:
            if self.context.messages:
                last_message = self.context.messages[0]
                payload["conversation_summary"].update(
                    {
                        "last_message_speaker": (
                            "Ken" if last_message.is_from_me else "Other"
                        ),
                        "last_message_preview": _clip_context_message(
                            last_message.body_text,
                            limit=280,
                        ),
                        "last_message_ref_hash": last_message.message_ref_hash,
                    }
                )
            payload["context_preview"] = [
                {
                    "index": index,
                    "speaker": "Ken" if message.is_from_me else "Other",
                    "is_from_me": message.is_from_me,
                    "message_ref_hash": message.message_ref_hash,
                    "body_text": _clip_context_message(message.body_text, limit=900),
                }
                for index, message in enumerate(
                    self.context.messages[: max(1, min(context_preview_limit, 10))],
                    start=1,
                )
            ]
        return payload


async def create_imessage_draft_proposal(
    *,
    principal_id: str = "ken",
    reply_goal: str | None = None,
    approval_id: str | None = None,
    max_context_messages: int = DEFAULT_MAX_CONTEXT_MESSAGES,
    vault_root: str | Path | None = None,
    bluebubbles_client: SparkIMessageBodyClient | None = None,
    approved_chat_guid: str | None = None,
    draft_text_override: str | None = None,
    personality_memory_rows: list[dict[str, object]] | None = None,
    llm_call: SparkLLMCall | None = None,
) -> SparkDraftProposal:
    """Create a human-reviewable draft from approved iMessage runtime context."""

    root = _vault_root(vault_root)
    records = load_approved_voice_sources(root, principal_id)
    guidance = load_spark_voice_guidance(root, principal_id)
    auto_context = _load_auto_prompt_context(root)
    record = _select_approved_imessage_record(records, approval_id=approval_id)
    context = await load_approved_imessage_context(
        record=record,
        max_context_messages=max_context_messages,
        bluebubbles_client=bluebubbles_client,
        approved_chat_guid=approved_chat_guid,
    )
    sensitivity = _scan_context_sensitivity(
        context=context,
        record=record,
        reply_goal=reply_goal,
    )
    if sensitivity.blocked:
        raise SparkDraftPolicyError(
            "sensitivity_blocked:" + ",".join(sensitivity.blocked_topics)
        )

    override = _draft_text_override(draft_text_override)
    if override:
        draft_text = override
        draft_engine = "human_override"
        engine_warnings: tuple[str, ...] = ("review_ui_override",)
    else:
        draft_text, draft_engine, engine_warnings = await _draft_from_context(
            reply_goal=reply_goal,
            guidance=guidance,
            auto_context=auto_context,
            personality_memory_rows=personality_memory_rows or [],
            context=context,
            sensitivity_warnings=sensitivity.warnings,
            llm_call=llm_call,
        )

    return SparkDraftProposal(
        principal_id=principal_id,
        draft_text=draft_text,
        context=context,
        conversation_summary=_conversation_summary(
            record=record,
            context=context,
            personality_memory_rows=personality_memory_rows or [],
        ),
        draft_quality=_draft_quality_scorecard(
            draft_text=draft_text,
            guidance=guidance,
            personality_memory_rows=personality_memory_rows or [],
        ),
        source_readiness=_source_readiness(records=records, selected_record=record),
        warnings=(
            "draft_only_no_send",
            "human_approval_required",
            "runtime_context_not_stored",
            *sensitivity.warnings,
            *engine_warnings,
        ),
        detected_sensitivity=tuple(sensitivity.detected_topics),
        blocked_sensitivity=tuple(sensitivity.blocked_topics),
        draft_engine=draft_engine,
    )


def apply_draft_text_override(
    proposal: SparkDraftProposal,
    draft_text_override: str | None,
) -> SparkDraftProposal:
    """Return a copy with reviewer-edited text when an override is present."""

    override = _draft_text_override(draft_text_override)
    if not override:
        return proposal

    warnings = (*proposal.warnings, "review_ui_override")
    return SparkDraftProposal(
        principal_id=proposal.principal_id,
        draft_text=override,
        context=proposal.context,
        conversation_summary=proposal.conversation_summary,
        draft_quality=_draft_quality_scorecard(
            draft_text=override,
            guidance=None,
            personality_memory_rows=[],
        ),
        source_readiness=proposal.source_readiness,
        warnings=tuple(dict.fromkeys(warnings)),
        detected_sensitivity=proposal.detected_sensitivity,
        blocked_sensitivity=proposal.blocked_sensitivity,
        draft_engine="human_override",
        draft_version=proposal.draft_version,
        can_send=proposal.can_send,
        requires_human_approval=proposal.requires_human_approval,
    )


async def load_approved_imessage_context(
    *,
    record: SparkApprovedSourceRecord,
    max_context_messages: int = DEFAULT_MAX_CONTEXT_MESSAGES,
    bluebubbles_client: SparkIMessageBodyClient | None = None,
    approved_chat_guid: str | None = None,
) -> SparkDraftContext:
    """Load approved iMessage bodies as runtime-only context."""

    if record.source != "imessage":
        raise SparkDraftPolicyError("approved source must be imessage")
    if not record.decision_approved:
        raise SparkDraftPolicyError("iMessage source approval is not checked")

    plan = plan_approved_corpus_ingest(
        SparkCorpusApproval(
            principal_id=record.principal_id,
            source=record.source,
            approval_id=record.approval_id,
            thread_kind=record.thread_kind,
            relationship_marked=record.relationship_marked,
            relationship_approved=record.relationship_approved,
            legal_marked=record.legal_marked,
            include_inbound_runtime_context=True,
            max_messages=_effective_limit(
                requested=record.requested_max_messages,
                max_context_messages=max_context_messages,
            ),
        )
    )
    if not plan.allowed or not plan.runtime_context_allowed:
        raise SparkDraftPolicyError(plan.reason)

    chat_guid = approved_chat_guid or _approved_chat_guid(record)
    client = bluebubbles_client or BlueBubblesReadOnlyClient()
    try:
        messages = await client.approved_messages_for_chat(
            chat_guid=chat_guid,
            limit=plan.max_messages,
        )
    except (BlueBubblesConfigError, BlueBubblesPolicyError):
        raise
    except BlueBubblesClientError as exc:
        raise SparkDraftContextError("approved_imessage_context_load_failed") from exc
    except Exception as exc:
        raise SparkDraftContextError("approved_imessage_context_load_failed") from exc

    runtime_messages = tuple(
        SparkRuntimeMessage(
            message_ref_hash=message.message_ref_hash,
            is_from_me=message.is_from_me,
            body_text=message.body_text,
        )
        for message in messages
    )
    return SparkDraftContext(
        principal_id=record.principal_id,
        approval_ref_hash=record.approval_ref_hash,
        source_reference_hash=record.source_reference_hash,
        chat_guid_hash=_sha256_text(chat_guid),
        messages=runtime_messages,
    )


def _select_approved_imessage_record(
    records: tuple[SparkApprovedSourceRecord, ...],
    *,
    approval_id: str | None,
) -> SparkApprovedSourceRecord:
    candidates = [record for record in records if record.source == "imessage"]
    if approval_id:
        for record in candidates:
            if record.approval_id == approval_id:
                return record
        raise SparkDraftPolicyError("requested iMessage approval was not found")
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise SparkDraftPolicyError("no approved iMessage source found")
    raise SparkDraftPolicyError("approval_id is required for multiple iMessage sources")


def _conversation_summary(
    *,
    record: SparkApprovedSourceRecord,
    context: SparkDraftContext,
    personality_memory_rows: list[dict[str, object]],
) -> SparkDraftConversationSummary:
    target_label, confidence = _reply_target_label(record, personality_memory_rows)
    return SparkDraftConversationSummary(
        channel="iMessage",
        voice_principal_label=_principal_label(context.principal_id),
        reply_target_label=target_label,
        reply_target_confidence=confidence,
    )


def _reply_target_label(
    record: SparkApprovedSourceRecord,
    personality_memory_rows: list[dict[str, object]],
) -> tuple[str, str]:
    if record.source_reference_label:
        return record.source_reference_label, "approved_source_label"
    relationship_labels = []
    for row in personality_memory_rows:
        if str(row.get("kind") or "").strip().lower() != "relationship":
            continue
        match = RELATIONSHIP_MEMORY.fullmatch(str(row.get("content") or "").strip())
        if match:
            relationship_labels.append(match.group("label").strip())
    unique = sorted({label for label in relationship_labels if label})
    if len(unique) == 1:
        return unique[0], "personality_memory"
    return "Approved one-to-one iMessage thread", "fallback_thread"


def _principal_label(principal_id: str) -> str:
    clean = re.sub(r"[^a-z0-9 _-]+", " ", principal_id.strip().lower())
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        return "Ken"
    return " ".join(part[:1].upper() + part[1:] for part in clean.split(" "))


def _source_readiness(
    *,
    records: tuple[SparkApprovedSourceRecord, ...],
    selected_record: SparkApprovedSourceRecord,
) -> tuple[SparkDraftSourceReadiness, ...]:
    statuses: list[SparkDraftSourceReadiness] = []
    seen_sources = set()
    for record in records:
        seen_sources.add(record.source)
        if record.source == "imessage":
            status = (
                "live_runtime_context"
                if record.approval_id == selected_record.approval_id
                else "approved_not_selected"
            )
            detail = (
                "Approved iMessage thread is feeding this draft at runtime."
                if status == "live_runtime_context"
                else "Approved iMessage source exists but was not selected."
            )
            statuses.append(
                SparkDraftSourceReadiness(
                    source="imessage",
                    channel="Text",
                    status=status,
                    detail=detail,
                )
            )
        elif record.source == "gmail":
            statuses.append(
                SparkDraftSourceReadiness(
                    source="gmail",
                    channel="Email",
                    status="voice_profile_only",
                    detail=(
                        "Approved sent mail can shape Ken's email voice; "
                        "live email reply context is not wired into draft generation yet."
                    ),
                )
            )
        elif record.source == "ai_export":
            statuses.append(
                SparkDraftSourceReadiness(
                    source="ai_export",
                    channel="AI chat",
                    status="voice_profile_only",
                    detail="Approved export can shape voice, not live reply context.",
                )
            )
        elif record.source == "intake":
            statuses.append(
                SparkDraftSourceReadiness(
                    source="intake",
                    channel="Intake",
                    status="voice_profile_only",
                    detail="Approved intake answers can shape voice and guardrails.",
                )
            )
    if "gmail" not in seen_sources:
        statuses.append(
            SparkDraftSourceReadiness(
                source="gmail",
                channel="Email",
                status="not_configured",
                detail="No approved Gmail source record is available for this principal.",
            )
        )
    return tuple(statuses)


def _draft_quality_scorecard(
    *,
    draft_text: str,
    guidance: SparkVoiceGuidance | None,
    personality_memory_rows: list[dict[str, object]],
) -> SparkDraftQualityScorecard:
    text = draft_text.strip()
    lower = text.lower()
    words = re.findall(r"\b[\w']+\b", text)
    recurring_phrases = tuple(guidance.recurring_phrases if guidance else ())
    memory_items = personality_memory_prompt_items(personality_memory_rows)

    checks = (
        SparkDraftQualityCheck(
            key="length",
            label="Short enough",
            passed=2 <= len(words) <= 85,
            detail=f"{len(words)} words; Spark should stay short to medium.",
        ),
        SparkDraftQualityCheck(
            key="silent_memory",
            label="No internal labels",
            passed=not re.search(
                r"\b(memory|policy|approval|guardrail|sensitivity|runtime context)\b",
                lower,
            ),
            detail="The draft should not mention hidden memory, policy, or review rails.",
        ),
        SparkDraftQualityCheck(
            key="not_robotic",
            label="Not robotic",
            passed=not _robotic_wrapup(lower),
            detail="Avoids canned assistant closings and formal wrap-ups.",
        ),
        SparkDraftQualityCheck(
            key="natural_text",
            label="Text-message natural",
            passed=("\n" not in text or len(text.splitlines()) <= 4)
            and not re.search(r"\b(sincerely|best regards|dear\s+\w+)\b", lower),
            detail="Reads like a text, not an email template.",
        ),
        SparkDraftQualityCheck(
            key="actionable",
            label="Clear next beat",
            passed=_has_concrete_next_beat(lower),
            detail="Gives a concrete acknowledgement or next action.",
        ),
        SparkDraftQualityCheck(
            key="voice_memory_used",
            label="Voice memory available",
            passed=bool(memory_items or recurring_phrases),
            detail="Reviewed voice memory or recurring phrases were available to the prompt.",
        ),
    )
    score = round(sum(1 for check in checks if check.passed) / len(checks) * 100)
    if score >= 85:
        verdict = "strong"
    elif score >= 70:
        verdict = "review"
    else:
        verdict = "needs_edit"
    return SparkDraftQualityScorecard(score=score, verdict=verdict, checks=checks)


def _robotic_wrapup(lower_text: str) -> bool:
    return bool(
        re.search(
            r"\b("
            r"please let me know if you have any questions|"
            r"i hope this message finds you well|"
            r"i would be happy to assist|"
            r"as an ai|"
            r"moving forward|"
            r"circle back"
            r")\b",
            lower_text,
        )
    )


def _has_concrete_next_beat(lower_text: str) -> bool:
    return bool(
        re.search(
            r"\b("
            r"i('| a)?m|"
            r"i will|"
            r"i can|"
            r"let me|"
            r"we can|"
            r"happy to|"
            r"got it|"
            r"sounds|"
            r"fair enough|"
            r"here"
            r")\b",
            lower_text,
        )
    )


def _draft_from_goal(
    *,
    reply_goal: str | None,
    guidance: SparkVoiceGuidance,
) -> str:
    goal = _clean_reply_goal(reply_goal)
    if goal:
        return _ensure_sentence(goal)

    text_style = guidance.channel_style.get("Text", "").lower()
    if "less formal" in text_style:
        return "Got it. Let me take a look and see what actually makes sense."
    return "Thank you. I will review this and follow up with what actually makes sense."


async def _draft_from_context(
    *,
    reply_goal: str | None,
    guidance: SparkVoiceGuidance,
    auto_context: AutoSparkPromptContext,
    personality_memory_rows: list[dict[str, object]],
    context: SparkDraftContext,
    sensitivity_warnings: tuple[str, ...],
    llm_call: SparkLLMCall | None,
) -> tuple[str, str, tuple[str, ...]]:
    if not _env_bool(SPARK_DRAFT_LLM_ENABLED_ENV, default=True):
        return (
            _draft_from_goal(reply_goal=reply_goal, guidance=guidance),
            "deterministic_v0",
            ("deterministic_v0_no_llm",),
        )

    try:
        raw = await _call_spark_llm(
            reply_goal=reply_goal,
            guidance=guidance,
            auto_context=auto_context,
            personality_memory_rows=personality_memory_rows,
            context=context,
            sensitivity_warnings=sensitivity_warnings,
            llm_call=llm_call,
        )
        draft = _clean_llm_draft(raw)
        if not draft:
            raise SparkDraftContextError("spark_llm_empty_draft")
        return draft, "gateway_llm", ("llm_generated",)
    except Exception as exc:
        if _env_bool(SPARK_DRAFT_LLM_REQUIRED_ENV, default=False):
            raise SparkDraftContextError("spark_llm_draft_failed") from exc
        return (
            _draft_from_goal(reply_goal=reply_goal, guidance=guidance),
            "deterministic_v0",
            ("llm_unavailable_deterministic_fallback",),
        )


async def _call_spark_llm(
    *,
    reply_goal: str | None,
    guidance: SparkVoiceGuidance,
    auto_context: AutoSparkPromptContext,
    personality_memory_rows: list[dict[str, object]],
    context: SparkDraftContext,
    sensitivity_warnings: tuple[str, ...],
    llm_call: SparkLLMCall | None,
) -> str:
    provider = os.environ.get(SPARK_DRAFT_LLM_PROVIDER_ENV, "anthropic").strip()
    model = os.environ.get(SPARK_DRAFT_LLM_MODEL_ENV, CLAUDE_FAST).strip()
    timeout_s = _env_int(SPARK_DRAFT_LLM_TIMEOUT_ENV, default=45)
    call = llm_call or call_gateway_cloud
    return await call(
        provider=provider,
        model=model,
        system_prompt=_spark_draft_system_prompt(
            guidance,
            auto_context,
            personality_memory_rows,
        ),
        user_message=_spark_draft_user_message(
            reply_goal=reply_goal,
            context=context,
            sensitivity_warnings=sensitivity_warnings,
        ),
        max_tokens=700,
        temperature=0.35,
        timeout_s=timeout_s,
        idempotency_key=_draft_idempotency_key(context, reply_goal, auto_context),
    )


def personality_memory_prompt_items(
    rows: list[dict[str, object]],
    *,
    max_items: int = PERSONALITY_MEMORY_MAX_PROMPT_LINES,
) -> list[SparkPersonalityMemoryPromptItem]:
    items: list[SparkPersonalityMemoryPromptItem] = []
    for row in rows:
        raw_kind = str(row.get("kind") or "memory").strip().lower()
        if raw_kind not in PERSONALITY_MEMORY_DRAFT_KINDS:
            continue
        content = _clean_personality_memory_content(
            str(row.get("content") or ""),
            kind=raw_kind,
        )
        if not content:
            continue
        evidence_ref_hash = row.get("evidence_ref_hash")
        items.append(
            SparkPersonalityMemoryPromptItem(
                kind=raw_kind,
                content=content,
                source=str(row.get("source") or "unknown"),
                evidence_ref_hash=(
                    str(evidence_ref_hash).strip() if evidence_ref_hash else None
                ),
            )
        )
        if len(items) >= max_items:
            break
    return items


def _personality_memory_prompt(rows: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for item in personality_memory_prompt_items(rows):
        kind = item.kind.replace("_", " ")
        lines.append(f"- {kind.title()}: {item.content}")
    return "\n".join(lines)


def _clean_personality_memory_content(value: str, *, kind: str) -> str:
    content = " ".join(value.strip().split())
    if not content or PERSONALITY_MEMORY_BLOCKED.search(content):
        return ""
    if kind == "relationship":
        match = RELATIONSHIP_MEMORY.fullmatch(content)
        if match:
            label = match.group("label").strip()
            relationship = match.group("relationship").strip()
            return f"{label} is Ken's {relationship}."
    return content[:240]


def _spark_draft_system_prompt(
    guidance: SparkVoiceGuidance,
    auto_context: AutoSparkPromptContext,
    personality_memory_rows: list[dict[str, object]],
) -> str:
    lines = [
        "You draft iMessage replies for Ken.",
        "Return only the draft text. Do not wrap it in JSON or markdown.",
        "Do not claim the message was sent.",
        "Do not quote the other person's private text unless Ken explicitly asks.",
        "Keep it short or medium length.",
        "Sound like Ken's best edited self.",
        f"Target voice: {', '.join(guidance.voice_markers)}.",
        f"Avoid: {', '.join(guidance.avoid_markers)}.",
        f"Recurring phrases, used sparingly: {', '.join(guidance.recurring_phrases)}.",
        "If uncertain, be clear that Ken needs to confirm.",
    ]
    if guidance.text_message_calibration:
        lines.extend(
            [
                "",
                "Ken text-message calibration:",
                *[
                    f"- {line}"
                    for line in _bounded_prompt_lines(
                        guidance.text_message_calibration,
                        max_lines=12,
                    )
                ],
            ]
        )
    memory_context = _personality_memory_prompt(personality_memory_rows)
    if memory_context:
        lines.extend(
            [
                "",
                "Approved Spark personality memory (reviewed; use silently):",
                memory_context,
                "Use approved personality memory for voice, relationship context, and preferences.",
                "Never mention memory, sensitivity labels, policy, approval requirements, or review requirements in the draft.",
                "The API already enforces draft-only human review, so write the human-facing message only.",
            ]
        )
    lines.extend(
        [
            "",
            "Auto operating context for this draft (internal; do not quote or expose):",
            *[f"- {line}" for line in auto_context.prompt_lines],
            "Use Auto context only for priorities, boundaries, and safety posture.",
            "If Auto context conflicts with Ken's principal voice file, Ken's voice file wins.",
        ]
    )
    return "\n".join(lines)


def _spark_draft_user_message(
    *,
    reply_goal: str | None,
    context: SparkDraftContext,
    sensitivity_warnings: tuple[str, ...],
) -> str:
    lines = [
        f"Principal: {context.principal_id}",
        f"Reply goal: {_clean_reply_goal(reply_goal) or 'Draft the next useful reply.'}",
        "Channel: iMessage text",
        "Context order: newest first",
        f"Sensitivity labels: {', '.join(sensitivity_warnings) or 'none'}",
        "",
        "Runtime thread context:",
    ]
    for index, message in enumerate(context.messages, start=1):
        speaker = "Ken" if message.is_from_me else "Other"
        body = _clip_context_message(message.body_text)
        lines.append(f"{index}. {speaker}: {body}")
    lines.extend(
        [
            "",
            "Write one draft reply Ken can review.",
            "No send action. No metadata. Draft text only.",
        ]
    )
    return "\n".join(lines)


def _scan_context_sensitivity(
    *,
    context: SparkDraftContext,
    record: SparkApprovedSourceRecord,
    reply_goal: str | None,
):
    try:
        guardrails = load_spark_guardrails()
        protected_topics = guardrails.protected_topics
    except Exception:
        protected_topics = [
            "legal",
            "medical",
            "custody",
            "minor",
            "relationship",
            "financial",
            "security",
        ]
    return scan_spark_draft_sensitivity(
        texts=[
            _clean_reply_goal(reply_goal),
            *(message.body_text for message in context.messages),
        ],
        protected_topics=protected_topics,
        relationship_marked=record.relationship_marked,
        relationship_approved=record.relationship_approved,
    )


def _load_auto_prompt_context(root: Path) -> AutoSparkPromptContext:
    try:
        return load_auto_spark_prompt_context(root)
    except AutoBrainConfigError as exc:
        raise SparkDraftConfigError("auto_spark_context_unavailable") from exc


def _draft_text_override(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _clean_llm_draft(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    text = re.sub(r"(?i)^draft\s*:\s*", "", text).strip()
    return text[:4000].strip()


def _clip_context_message(value: str, limit: int = 1200) -> str:
    clean = re.sub(r"\s+", " ", value).strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def _approved_chat_guid(record: SparkApprovedSourceRecord) -> str:
    env_names = (
        _approval_specific_env_name(record.approval_id),
        APPROVED_CHAT_GUID_ENV,
    )
    for env_name in env_names:
        value = _optional_secret(env_name)
        if value:
            return value
    raise SparkDraftConfigError("approved iMessage chat GUID is not configured")


def _approval_specific_env_name(approval_id: str) -> str:
    suffix = re.sub(r"[^A-Za-z0-9]+", "_", approval_id).strip("_").upper()
    return f"SPARK_IMESSAGE_APPROVED_CHAT_GUID_{suffix}"


def _optional_secret(name: str) -> str | None:
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    try:
        secret_value = get_secret(name)
    except Exception:
        return None
    return secret_value.strip() if secret_value and secret_value.strip() else None


def _effective_limit(*, requested: int, max_context_messages: int) -> int:
    request_cap = min(max(max_context_messages, 1), MAX_CONTEXT_MESSAGES)
    return min(max(requested, 1), request_cap)


def _clean_reply_goal(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _ensure_sentence(value: str) -> str:
    clean = value.strip()
    if not clean:
        return clean
    if clean[-1] in ".!?":
        return clean
    return f"{clean}."


def _bounded_prompt_lines(
    values: tuple[str, ...] | list[str],
    *,
    max_lines: int,
    max_chars: int = 180,
) -> list[str]:
    lines: list[str] = []
    for value in values:
        clean = re.sub(r"\s+", " ", value).strip().strip("\"'")
        if not clean:
            continue
        if len(clean) > max_chars:
            clean = clean[: max_chars - 3].rstrip() + "..."
        lines.append(clean)
        if len(lines) >= max_lines:
            break
    return lines


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def _draft_idempotency_key(
    context: SparkDraftContext,
    reply_goal: str | None,
    auto_context: AutoSparkPromptContext,
) -> str:
    raw = "|".join(
        [
            "spark-draft-v0.2",
            context.approval_ref_hash,
            context.source_reference_hash,
            context.chat_guid_hash,
            auto_context.prompt_sha256,
            _sha256_text(_clean_reply_goal(reply_goal)),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, *, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _vault_root(vault_root: str | Path | None) -> Path:
    raw = str(vault_root) if vault_root is not None else "~/jarvis-personality"
    return Path(raw).expanduser()
