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
from typing import Any, Protocol

from brain.config.secrets import get_secret
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

DRAFT_VERSION = "spark-imessage-draft/v0.1"
DEFAULT_MAX_CONTEXT_MESSAGES = 20
MAX_CONTEXT_MESSAGES = 50
APPROVED_CHAT_GUID_ENV = "SPARK_IMESSAGE_APPROVED_CHAT_GUID"


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
    draft_version: str = DRAFT_VERSION
    can_send: bool = False
    requires_human_approval: bool = True

    def to_payload(self) -> dict[str, Any]:
        return {
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
        }


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
) -> SparkDraftProposal:
    """Create a human-reviewable draft from approved iMessage runtime context."""

    root = _vault_root(vault_root)
    records = load_approved_voice_sources(root, principal_id)
    guidance = load_spark_voice_guidance(root, principal_id)
    record = _select_approved_imessage_record(records, approval_id=approval_id)
    context = await load_approved_imessage_context(
        record=record,
        max_context_messages=max_context_messages,
        bluebubbles_client=bluebubbles_client,
        approved_chat_guid=approved_chat_guid,
    )
    draft_text = _draft_text_override(draft_text_override) or _draft_from_goal(
        reply_goal=reply_goal,
        guidance=guidance,
    )
    return SparkDraftProposal(
        principal_id=principal_id,
        draft_text=draft_text,
        context=context,
        warnings=(
            "draft_only_no_send",
            "human_approval_required",
            "runtime_context_not_stored",
            "deterministic_v0_no_llm",
        ),
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
        return "Got it. I'll take a look and come back with a clear answer."
    return "Thank you. I will review this and follow up with a clear answer."


def _draft_text_override(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip()


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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def _vault_root(vault_root: str | Path | None) -> Path:
    raw = str(vault_root) if vault_root is not None else "~/jarvis-personality"
    return Path(raw).expanduser()
