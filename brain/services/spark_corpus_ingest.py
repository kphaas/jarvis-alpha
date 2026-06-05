"""Policy planner for approved Spark voice-corpus ingestion.

This module does not fetch BlueBubbles, Gmail, or export content. It only
turns a human approval record into an explicit ingest plan that downstream
workers can enforce before reading any body text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SparkCorpusSource = Literal["imessage", "gmail", "ai_export", "intake"]
SparkThreadKind = Literal["one_to_one", "group", "unknown"]


@dataclass(frozen=True, slots=True)
class SparkCorpusApproval:
    """Human approval envelope for a single corpus ingest request."""

    principal_id: str
    source: SparkCorpusSource
    approval_id: str
    thread_kind: SparkThreadKind = "unknown"
    thread_ref: str | None = None
    relationship_marked: bool = False
    relationship_approved: bool = False
    legal_marked: bool = False
    include_inbound_runtime_context: bool = False
    max_messages: int = 50


@dataclass(frozen=True, slots=True)
class SparkCorpusIngestPlan:
    """Read plan for later corpus workers."""

    allowed: bool
    reason: str
    principal_id: str
    source: SparkCorpusSource
    body_access_required: bool
    durable_voice_source: Literal["principal_sent_messages_only", "none"]
    runtime_context_allowed: bool
    allowed_operations: tuple[str, ...]
    blocked_operations: tuple[str, ...]
    redaction_rules: tuple[str, ...]
    max_messages: int


BASE_BLOCKED_OPERATIONS = (
    "send_message",
    "store_raw_thread",
    "store_inbound_message_text",
    "store_contact_names",
)
BASE_REDACTION_RULES = (
    "do_not_log_message_bodies",
    "do_not_log_contact_names",
    "hash_thread_ref_in_logs",
    "store_principal_sent_messages_only",
)


def plan_approved_corpus_ingest(
    approval: SparkCorpusApproval,
) -> SparkCorpusIngestPlan:
    """Build a fail-closed ingest plan from a human approval envelope."""

    denial = _denial_reason(approval)
    if denial:
        return _blocked_plan(approval, denial)

    operations = ["read_approved_source", "extract_principal_sent_messages"]
    if approval.include_inbound_runtime_context:
        operations.append("load_inbound_runtime_context")

    return SparkCorpusIngestPlan(
        allowed=True,
        reason="approved_principal_sent_messages_only",
        principal_id=approval.principal_id,
        source=approval.source,
        body_access_required=True,
        durable_voice_source="principal_sent_messages_only",
        runtime_context_allowed=approval.include_inbound_runtime_context,
        allowed_operations=tuple(operations),
        blocked_operations=BASE_BLOCKED_OPERATIONS,
        redaction_rules=BASE_REDACTION_RULES,
        max_messages=approval.max_messages,
    )


def _denial_reason(approval: SparkCorpusApproval) -> str | None:
    if not approval.principal_id.strip():
        return "principal_id_required"
    if not approval.approval_id.strip():
        return "approval_id_required"
    if approval.max_messages < 1:
        return "max_messages_must_be_positive"
    if approval.legal_marked:
        return "legal_marked_content_requires_manual_review"
    if approval.thread_kind != "one_to_one":
        return "phase_two_requires_one_to_one_thread"
    if approval.relationship_marked and not approval.relationship_approved:
        return "relationship_marked_content_requires_specific_approval"
    return None


def _blocked_plan(
    approval: SparkCorpusApproval,
    reason: str,
) -> SparkCorpusIngestPlan:
    return SparkCorpusIngestPlan(
        allowed=False,
        reason=reason,
        principal_id=approval.principal_id,
        source=approval.source,
        body_access_required=False,
        durable_voice_source="none",
        runtime_context_allowed=False,
        allowed_operations=(),
        blocked_operations=BASE_BLOCKED_OPERATIONS,
        redaction_rules=BASE_REDACTION_RULES,
        max_messages=max(approval.max_messages, 0),
    )
