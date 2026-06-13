"""Sanitized Spark voice proposal builder.

The proposal builder reads only approved Spark source records and returns a
review packet with counts, hashes, and policy facts. It must never return raw
message bodies, sender/recipient names, subjects, snippets, source paths, or
contact labels.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from brain.services.spark_corpus_ingest import (
    SparkCorpusApproval,
    SparkCorpusSource,
    SparkThreadKind,
    plan_approved_corpus_ingest,
)

DEFAULT_PERSONALITY_VAULT = "~/jarvis-personality"
PROPOSAL_VERSION = "spark-voice-proposal/v0.1"
REDACTION_POLICY_VERSION = "spark-redaction/v0.1"
GMAIL_SENT_QUERY = "in:sent newer_than:180d"
DEFAULT_GMAIL_MAX_MESSAGES = 250

SourceSummaryStatus = Literal[
    "verified",
    "summarized",
    "planned",
    "deferred",
    "denied",
    "unavailable",
]


class SparkVoiceIngestError(RuntimeError):
    """Raised when approved Spark voice source metadata cannot be loaded."""


class GmailMessageLike(Protocol):
    body_text: str


class GmailVoiceClient(Protocol):
    async def list_message_ids(self, query: str, max_results: int) -> list[str]: ...

    async def get_message(self, message_id: str) -> GmailMessageLike: ...


@dataclass(frozen=True, slots=True)
class SparkVoiceGuidance:
    voice_markers: tuple[str, ...]
    recurring_phrases: tuple[str, ...]
    avoid_markers: tuple[str, ...]
    channel_style: dict[str, str]
    text_message_calibration: tuple[str, ...]
    accessibility_style: tuple[str, ...]
    judgment_style: dict[str, str]

    def to_payload(self) -> dict[str, Any]:
        return {
            "voice_markers": list(self.voice_markers),
            "recurring_phrases": list(self.recurring_phrases),
            "avoid_markers": list(self.avoid_markers),
            "channel_style": dict(self.channel_style),
            "text_message_calibration": list(self.text_message_calibration),
            "accessibility_style": list(self.accessibility_style),
            "judgment_style": dict(self.judgment_style),
        }


@dataclass(frozen=True, slots=True)
class SparkApprovedSourceRecord:
    principal_id: str
    source: SparkCorpusSource
    approval_id: str
    source_reference_hash: str
    source_reference_path: Path | None
    source_sha256: str | None
    thread_kind: SparkThreadKind
    requested_max_messages: int
    requested_date_window: str | None
    relationship_marked: bool
    relationship_approved: bool
    legal_marked: bool
    decision_approved: bool

    @property
    def approval_ref_hash(self) -> str:
        return _sha256_text(self.approval_id)


@dataclass(frozen=True, slots=True)
class SparkCorpusTextStats:
    document_count: int
    total_characters: int
    total_words: int
    total_lines: int
    question_marks: int
    exclamation_marks: int
    average_words_per_document: float

    @classmethod
    def empty(cls) -> SparkCorpusTextStats:
        return cls(
            document_count=0,
            total_characters=0,
            total_words=0,
            total_lines=0,
            question_marks=0,
            exclamation_marks=0,
            average_words_per_document=0.0,
        )

    @classmethod
    def from_texts(cls, texts: list[str]) -> SparkCorpusTextStats:
        word_counts = [_word_count(text) for text in texts]
        total_words = sum(word_counts)
        document_count = len(texts)
        average_words = total_words / document_count if document_count else 0.0
        return cls(
            document_count=document_count,
            total_characters=sum(len(text) for text in texts),
            total_words=total_words,
            total_lines=sum(max(1, text.count("\n") + 1) for text in texts),
            question_marks=sum(text.count("?") for text in texts),
            exclamation_marks=sum(text.count("!") for text in texts),
            average_words_per_document=round(average_words, 2),
        )

    def to_payload(self) -> dict[str, int | float]:
        return {
            "document_count": self.document_count,
            "total_characters": self.total_characters,
            "total_words": self.total_words,
            "total_lines": self.total_lines,
            "question_marks": self.question_marks,
            "exclamation_marks": self.exclamation_marks,
            "average_words_per_document": self.average_words_per_document,
        }


@dataclass(frozen=True, slots=True)
class SparkVoiceEvidenceSummary:
    source: SparkCorpusSource
    approval_ref_hash: str
    source_reference_hash: str
    status: SourceSummaryStatus
    retained_examples: int
    runtime_context_messages: int
    body_access_performed: bool
    text_stats: SparkCorpusTextStats
    notes: tuple[str, ...]
    verified_source_sha256: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": self.source,
            "approval_ref_hash": self.approval_ref_hash,
            "source_reference_hash": self.source_reference_hash,
            "status": self.status,
            "retained_examples": self.retained_examples,
            "runtime_context_messages": self.runtime_context_messages,
            "body_access_performed": self.body_access_performed,
            "redaction_policy_version": REDACTION_POLICY_VERSION,
            "text_stats": self.text_stats.to_payload(),
            "notes": list(self.notes),
        }
        if self.verified_source_sha256:
            payload["verified_source_sha256"] = self.verified_source_sha256
        return payload


@dataclass(frozen=True, slots=True)
class SparkVoiceProfileProposal:
    principal_id: str
    source_summaries: tuple[SparkVoiceEvidenceSummary, ...]
    voice_guidance: SparkVoiceGuidance
    guardrails: tuple[str, ...]
    next_steps: tuple[str, ...]
    proposal_version: str = PROPOSAL_VERSION

    def to_payload(self) -> dict[str, Any]:
        return {
            "proposal_version": self.proposal_version,
            "principal_id": self.principal_id,
            "source_summaries": [
                summary.to_payload() for summary in self.source_summaries
            ],
            "voice_guidance": self.voice_guidance.to_payload(),
            "guardrails": list(self.guardrails),
            "next_steps": list(self.next_steps),
        }

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_payload(), indent=indent, sort_keys=True)


async def build_spark_voice_profile_proposal(
    *,
    vault_root: str | Path | None = None,
    principal_id: str = "ken",
    gmail_client: GmailVoiceClient | None = None,
    live_gmail: bool = False,
) -> SparkVoiceProfileProposal:
    """Build a sanitized review proposal from approved Spark source records."""

    root = _vault_root(vault_root)
    records = load_approved_voice_sources(root, principal_id)
    guidance = load_spark_voice_guidance(root, principal_id)
    summaries = [
        await _summarize_source_record(
            record,
            gmail_client=gmail_client,
            live_gmail=live_gmail,
        )
        for record in records
    ]
    return SparkVoiceProfileProposal(
        principal_id=principal_id,
        source_summaries=tuple(summaries),
        voice_guidance=guidance,
        guardrails=(
            "no_raw_message_bodies",
            "no_email_subjects_senders_or_snippets",
            "no_contact_names_or_relationship_labels",
            "no_source_paths",
            "no_inbound_durable_text",
            "draft_only_no_send",
            "human_review_required_before_memory_write",
        ),
        next_steps=(
            "review_sanitized_proposal",
            "approve_or_edit_voice_profile_changes_in_ui",
            "configure_approved_imessage_chat_guid_for_live_draft_context",
        ),
    )


def load_approved_voice_sources(
    vault_root: str | Path | None = None,
    principal_id: str = "ken",
) -> tuple[SparkApprovedSourceRecord, ...]:
    """Load approved Spark source records for one principal."""

    root = _vault_root(vault_root)
    principal_root = root / "spark" / "principals" / principal_id
    source_records = _parse_source_records(
        _read_required(principal_root / "sources.yml")
    )
    approvals: list[SparkApprovedSourceRecord] = []
    for source_record in source_records:
        if source_record.get("status") != "approved":
            continue
        record_path = root / str(source_record["record"])
        fields = _parse_markdown_tables(_read_required(record_path))
        approvals.append(
            _approval_from_fields(
                principal_id=principal_id,
                fallback_approval_id=str(source_record["id"]),
                fallback_source=str(source_record["source"]),
                fields=fields,
            )
        )
    return tuple(approvals)


def load_spark_voice_guidance(
    vault_root: str | Path | None = None,
    principal_id: str = "ken",
) -> SparkVoiceGuidance:
    root = _vault_root(vault_root)
    text = _read_required(root / "spark" / "principals" / principal_id / "voice.md")
    return SparkVoiceGuidance(
        voice_markers=tuple(_list_after_label(text, "Ken-approved voice markers:")),
        recurring_phrases=tuple(
            _list_after_label(text, "Ken-approved recurring phrases:")
        ),
        avoid_markers=tuple(_list_after_label(text, "Avoid sounding:")),
        channel_style=_table_after_heading(text, "## Channel Style"),
        text_message_calibration=tuple(
            _bullets_after_heading(text, "## Text Message Calibration")
        ),
        accessibility_style=tuple(_list_after_label(text, "Prefer:")),
        judgment_style=_table_after_heading(text, "## Judgment Style"),
    )


async def _summarize_source_record(
    record: SparkApprovedSourceRecord,
    *,
    gmail_client: GmailVoiceClient | None,
    live_gmail: bool,
) -> SparkVoiceEvidenceSummary:
    plan = plan_approved_corpus_ingest(
        SparkCorpusApproval(
            principal_id=record.principal_id,
            source=record.source,
            approval_id=record.approval_id,
            thread_kind=record.thread_kind,
            relationship_marked=record.relationship_marked,
            relationship_approved=record.relationship_approved,
            legal_marked=record.legal_marked,
            max_messages=record.requested_max_messages,
        )
    )
    if not record.decision_approved:
        return _empty_summary(record, status="denied", notes=("approval_not_checked",))
    if not plan.allowed:
        return _empty_summary(record, status="denied", notes=(plan.reason,))
    if record.source == "ai_export":
        return _summarize_ai_export(record)
    if record.source == "gmail":
        return await _summarize_gmail(record, gmail_client, live_gmail)
    if record.source == "imessage":
        return _empty_summary(
            record,
            status="deferred",
            notes=(
                "bluebubbles_body_reader_available_for_draft_runtime_context",
                "live_imessage_body_access_not_requested",
            ),
        )
    return _empty_summary(
        record,
        status="planned",
        notes=("source_runner_not_implemented",),
    )


def _summarize_ai_export(
    record: SparkApprovedSourceRecord,
) -> SparkVoiceEvidenceSummary:
    if record.source_reference_path is None:
        return _empty_summary(
            record,
            status="unavailable",
            notes=("ai_export_source_path_unavailable",),
        )
    try:
        body = record.source_reference_path.read_bytes()
    except FileNotFoundError:
        return _empty_summary(
            record,
            status="unavailable",
            notes=("ai_export_source_file_missing",),
        )
    actual_sha256 = hashlib.sha256(body).hexdigest()
    if record.source_sha256 and actual_sha256 != record.source_sha256:
        return _empty_summary(
            record,
            status="denied",
            notes=("ai_export_hash_mismatch",),
            body_access_performed=True,
        )
    text = body.decode("utf-8", errors="replace")
    return SparkVoiceEvidenceSummary(
        source=record.source,
        approval_ref_hash=record.approval_ref_hash,
        source_reference_hash=record.source_reference_hash,
        status="verified",
        retained_examples=1,
        runtime_context_messages=0,
        body_access_performed=True,
        text_stats=SparkCorpusTextStats.from_texts([text]),
        notes=("ai_export_hash_verified", "sanitized_statistics_only"),
        verified_source_sha256=actual_sha256,
    )


async def _summarize_gmail(
    record: SparkApprovedSourceRecord,
    gmail_client: GmailVoiceClient | None,
    live_gmail: bool,
) -> SparkVoiceEvidenceSummary:
    if not live_gmail:
        return _empty_summary(
            record,
            status="planned",
            notes=("live_gmail_body_access_not_requested",),
        )
    if gmail_client is None:
        return _empty_summary(
            record,
            status="unavailable",
            notes=("gmail_client_required_for_live_ingest",),
        )
    max_results = min(record.requested_max_messages, DEFAULT_GMAIL_MAX_MESSAGES)
    try:
        message_ids = await gmail_client.list_message_ids(
            _gmail_query(record),
            max_results=max_results,
        )
        bodies = [
            (await gmail_client.get_message(message_id)).body_text
            for message_id in message_ids[:max_results]
        ]
    except Exception as exc:
        raise SparkVoiceIngestError("gmail_ingest_failed") from exc

    return SparkVoiceEvidenceSummary(
        source=record.source,
        approval_ref_hash=record.approval_ref_hash,
        source_reference_hash=record.source_reference_hash,
        status="summarized",
        retained_examples=len(bodies),
        runtime_context_messages=0,
        body_access_performed=True,
        text_stats=SparkCorpusTextStats.from_texts(bodies),
        notes=("sent_mail_only", "sanitized_statistics_only"),
    )


def _empty_summary(
    record: SparkApprovedSourceRecord,
    *,
    status: SourceSummaryStatus,
    notes: tuple[str, ...],
    body_access_performed: bool = False,
) -> SparkVoiceEvidenceSummary:
    return SparkVoiceEvidenceSummary(
        source=record.source,
        approval_ref_hash=record.approval_ref_hash,
        source_reference_hash=record.source_reference_hash,
        status=status,
        retained_examples=0,
        runtime_context_messages=0,
        body_access_performed=body_access_performed,
        text_stats=SparkCorpusTextStats.empty(),
        notes=notes,
    )


def _approval_from_fields(
    *,
    principal_id: str,
    fallback_approval_id: str,
    fallback_source: str,
    fields: dict[str, str],
) -> SparkApprovedSourceRecord:
    source_reference = fields.get("source_reference", "")
    return SparkApprovedSourceRecord(
        principal_id=principal_id,
        source=_source(fields.get("source") or fallback_source),
        approval_id=fields.get("approval_id") or fallback_approval_id,
        source_reference_hash=_sha256_text(source_reference),
        source_reference_path=_source_path(source_reference),
        source_sha256=_optional_hash(fields.get("source_sha_256")),
        thread_kind=_thread_kind(fields.get("thread_kind")),
        requested_max_messages=_max_messages(fields.get("requested_max_messages")),
        requested_date_window=fields.get("requested_date_window") or None,
        relationship_marked=_is_yes(fields.get("relationship_marked")),
        relationship_approved=_is_yes(
            fields.get("relationship_specific_approval_granted")
        ),
        legal_marked=_is_yes(fields.get("legal_or_custody_content")),
        decision_approved=fields.get("decision_approved") == "true",
    )


def _parse_source_records(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_records = False
    for line in text.splitlines():
        if line.startswith("approved_source_records:"):
            in_records = True
            continue
        if not in_records:
            continue
        if line and not line.startswith(" ") and not line.startswith("-"):
            break
        if line.startswith("  - "):
            if current:
                records.append(current)
            current = {}
            _store_key_value(current, line.removeprefix("  - "))
        elif current is not None and line.startswith("    "):
            _store_key_value(current, line.strip())
    if current:
        records.append(current)
    return records


def _parse_markdown_tables(text: str) -> dict[str, str]:
    fields: dict[str, str] = {
        "decision_approved": "true"
        if re.search(r"(?m)^-\s+\[x\]\s+Approved", text)
        else "false"
    }
    for line in text.splitlines():
        match = re.match(r"^\|\s*(?P<key>[^|]+?)\s*\|\s*(?P<value>[^|]+?)\s*\|$", line)
        if not match:
            continue
        key = _normalize_key(match.group("key"))
        value = match.group("value").strip()
        if key in {"field", "flag", "use"} or set(value) <= {"-", " "}:
            continue
        fields[key] = value
    return fields


def _list_after_label(text: str, label: str) -> list[str]:
    lines = text.splitlines()
    values: list[str] = []
    capture = False
    for line in lines:
        if line.strip() == label:
            capture = True
            continue
        if not capture:
            continue
        if line.startswith("#") or (values and not line.strip()):
            break
        if line.startswith("- "):
            values.append(line.removeprefix("- ").strip())
    return values


def _table_after_heading(text: str, heading: str) -> dict[str, str]:
    section = _section_after_heading(text, heading)
    rows: dict[str, str] = {}
    for line in section.splitlines():
        match = re.match(r"^\|\s*(?P<key>[^|]+?)\s*\|\s*(?P<value>[^|]+?)\s*\|$", line)
        if not match:
            continue
        key = match.group("key").strip()
        value = match.group("value").strip()
        if key.lower() in {"channel", "situation"} or set(value) <= {"-", " "}:
            continue
        rows[key] = value
    return rows


def _bullets_after_heading(text: str, heading: str) -> list[str]:
    section = _section_after_heading(text, heading)
    values: list[str] = []
    for line in section.splitlines():
        if line.startswith("- "):
            values.append(line.removeprefix("- ").strip())
    return values


def _section_after_heading(text: str, heading: str) -> str:
    _, _, tail = text.partition(heading)
    if not tail:
        return ""
    return tail.split("\n## ", 1)[0]


def _store_key_value(target: dict[str, str], line: str) -> None:
    if ":" not in line:
        return
    key, value = line.split(":", 1)
    target[key.strip()] = value.strip().strip("\"'")


def _source(value: str) -> SparkCorpusSource:
    if value not in {"imessage", "gmail", "ai_export", "intake"}:
        raise SparkVoiceIngestError(f"unsupported Spark source: {value}")
    return value  # type: ignore[return-value]


def _thread_kind(value: str | None) -> SparkThreadKind:
    normalized = (value or "unknown").strip().lower()
    if normalized not in {"one_to_one", "group", "none", "unknown"}:
        return "unknown"
    return normalized  # type: ignore[return-value]


def _source_path(value: str) -> Path | None:
    clean = _strip_markdown(value)
    if clean.startswith("/") or clean.startswith("~"):
        return Path(clean).expanduser()
    return None


def _optional_hash(value: str | None) -> str | None:
    clean = (value or "").strip().lower()
    return clean if re.fullmatch(r"[a-f0-9]{64}", clean) else None


def _max_messages(value: str | None) -> int:
    if not value:
        return 1
    match = re.search(r"\d+", value)
    if not match:
        return 1
    return max(1, int(match.group(0)))


def _gmail_query(record: SparkApprovedSourceRecord) -> str:
    if (record.requested_date_window or "").lower() == "last 180 days":
        return GMAIL_SENT_QUERY
    return GMAIL_SENT_QUERY


def _is_yes(value: str | None) -> bool:
    return (value or "").strip().lower().startswith("yes")


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def _strip_markdown(value: str) -> str:
    return value.strip().strip("`").strip()


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(_strip_markdown(value).encode("utf-8")).hexdigest()


def _vault_root(vault_root: str | Path | None) -> Path:
    raw = str(vault_root) if vault_root is not None else DEFAULT_PERSONALITY_VAULT
    return Path(raw).expanduser()


def _read_required(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SparkVoiceIngestError(f"missing Spark personality file: {path}") from exc
