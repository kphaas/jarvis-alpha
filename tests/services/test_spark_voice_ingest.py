from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from brain.services.spark_voice_ingest import (
    GMAIL_SENT_QUERY,
    build_spark_voice_profile_proposal,
    load_approved_voice_sources,
    load_spark_voice_guidance,
)


@dataclass(frozen=True)
class FakeGmailMessage:
    body_text: str


class FakeGmailClient:
    def __init__(self) -> None:
        self.queries: list[tuple[str, int]] = []
        self.message_ids: list[str] = ["msg-1", "msg-2"]
        self.messages = {
            "msg-1": FakeGmailMessage(
                "Sweta secret custody bank account private body text?"
            ),
            "msg-2": FakeGmailMessage(
                "Alice@example.com subject leak should stay inside the fake body!"
            ),
        }

    async def list_message_ids(self, query: str, max_results: int) -> list[str]:
        self.queries.append((query, max_results))
        return self.message_ids

    async def get_message(self, message_id: str) -> FakeGmailMessage:
        return self.messages[message_id]


@pytest.mark.asyncio
async def test_voice_proposal_sanitizes_live_gmail_and_ai_export(
    tmp_path: Path,
) -> None:
    vault_root, export_sha256 = _write_vault(tmp_path)
    gmail = FakeGmailClient()

    proposal = await build_spark_voice_profile_proposal(
        vault_root=vault_root,
        principal_id="ken",
        gmail_client=gmail,
        live_gmail=True,
    )

    payload = proposal.to_payload()
    serialized = json.dumps(payload).lower()
    for forbidden in (
        "sweta",
        "secret custody",
        "bank account",
        "private body text",
        "alice@example.com",
        str(tmp_path).lower(),
    ):
        assert forbidden not in serialized

    summaries = {summary["source"]: summary for summary in payload["source_summaries"]}
    assert summaries["gmail"]["status"] == "summarized"
    assert summaries["gmail"]["retained_examples"] == 2
    assert summaries["gmail"]["body_access_performed"] is True
    assert summaries["gmail"]["text_stats"]["document_count"] == 2
    assert summaries["ai_export"]["status"] == "verified"
    assert summaries["ai_export"]["verified_source_sha256"] == export_sha256
    assert summaries["imessage"]["status"] == "deferred"
    assert summaries["imessage"]["body_access_performed"] is False
    assert "no_raw_message_bodies" in payload["guardrails"]
    assert gmail.queries == [(GMAIL_SENT_QUERY, 250)]


@pytest.mark.asyncio
async def test_voice_proposal_defaults_to_no_gmail_body_access(
    tmp_path: Path,
) -> None:
    vault_root, _ = _write_vault(tmp_path)
    gmail = FakeGmailClient()

    proposal = await build_spark_voice_profile_proposal(
        vault_root=vault_root,
        principal_id="ken",
        gmail_client=gmail,
        live_gmail=False,
    )

    summaries = {
        summary["source"]: summary
        for summary in proposal.to_payload()["source_summaries"]
    }
    assert summaries["gmail"]["status"] == "planned"
    assert summaries["gmail"]["body_access_performed"] is False
    assert gmail.queries == []


def _write_vault(tmp_path: Path) -> tuple[Path, str]:
    export_path = tmp_path / "KEN_VOICE_SPARK.md"
    export_path.write_text(
        "This export contains Sweta and custody context but only stats may leave.",
        encoding="utf-8",
    )
    export_sha256 = hashlib.sha256(export_path.read_bytes()).hexdigest()
    principal_root = tmp_path / "spark" / "principals" / "ken"
    approvals = principal_root / "corpus_approvals"
    approvals.mkdir(parents=True)
    (principal_root / "sources.yml").write_text(
        """
version: 0.1.0
principal: ken
approved_source_records:
  - id: ken-imessage-sweta-20260605-001
    source: imessage
    record: spark/principals/ken/corpus_approvals/imessage.md
    status: approved
  - id: ken-ai-export-voice-spark-20260605-001
    source: ai_export
    record: spark/principals/ken/corpus_approvals/ai_export.md
    status: approved
  - id: ken-gmail-sent-180d-20260605-001
    source: gmail
    record: spark/principals/ken/corpus_approvals/gmail.md
    status: approved
durable_voice_sources:
  - sent_messages_only
""",
        encoding="utf-8",
    )
    (principal_root / "voice.md").write_text(
        """
# Ken Voice

Ken-approved voice markers:
- Optimistic
- Cheerful
- Playful

Ken-approved recurring phrases:
- cheers
- fair enough

Avoid sounding:
- Robotic
- Rambling

## Channel Style

| Channel | Rule |
|---|---|
| Text | Less formal |
| Email | More formal |

## Accessibility Style

Prefer:
- Bullets
- Visual structure

## Judgment Style

| Situation | Rule |
|---|---|
| Uncertainty | Admit uncertainty |
""",
        encoding="utf-8",
    )
    (approvals / "imessage.md").write_text(
        """
# Corpus Approval: Ken iMessage One-To-One Thread

| Field | Value |
|---|---|
| Approval ID | ken-imessage-sweta-20260605-001 |
| Principal | ken |
| Source | imessage |
| Source reference | relationship-thread-label: Sweta |
| Thread kind | one_to_one |
| Requested max messages | 200 |

| Flag | Value |
|---|---|
| Relationship-marked | yes |
| Relationship-specific approval granted | yes |
| Parent minor context approval granted | yes |
| Legal or custody content | block if detected |

- [x] Approved
""",
        encoding="utf-8",
    )
    (approvals / "ai_export.md").write_text(
        f"""
# Corpus Approval: Ken Voice Spark AI Export

| Field | Value |
|---|---|
| Approval ID | ken-ai-export-voice-spark-20260605-001 |
| Principal | ken |
| Source | ai_export |
| Source reference | `{export_path}` |
| Source SHA-256 | {export_sha256} |
| Thread kind | none |
| Requested max messages | n/a |

| Flag | Value |
|---|---|
| Relationship-marked | no |
| Relationship-specific approval granted | n/a |
| Legal or custody content | no |

- [x] Approved
""",
        encoding="utf-8",
    )
    (approvals / "gmail.md").write_text(
        """
# Corpus Approval: Ken Gmail Sent Mail 180-Day Scope

| Field | Value |
|---|---|
| Approval ID | ken-gmail-sent-180d-20260605-001 |
| Principal | ken |
| Source | gmail |
| Source reference | sent-mail query: last 180 days, no query exclusions |
| Thread kind | none |
| Requested max messages | 250 |
| Requested date window | last 180 days |

| Flag | Value |
|---|---|
| Relationship-marked | no query exclusions by Ken approval |
| Relationship-specific approval granted | no; separate approval required |
| Legal or custody content | no query exclusions by Ken approval; tag if detected |

- [x] Approved
""",
        encoding="utf-8",
    )
    return tmp_path, export_sha256


def test_voice_source_parser_reads_parent_minor_context_approval(
    tmp_path: Path,
) -> None:
    vault_root, _ = _write_vault(tmp_path)

    imessage = next(
        record
        for record in load_approved_voice_sources(vault_root, "ken")
        if record.source == "imessage"
    )

    assert imessage.parent_minor_context_approved is True


def test_voice_guidance_accepts_principal_neutral_approved_labels(
    tmp_path: Path,
) -> None:
    principal_root = tmp_path / "spark" / "principals" / "sweta"
    principal_root.mkdir(parents=True)
    (principal_root / "voice.md").write_text(
        """
# Sweta Voice

Approved voice markers:
- Warm
- Clear

Approved recurring phrases:
- sounds good
- let me check

Avoid sounding:
- Robotic

## Channel Style

| Channel | Rule |
|---|---|
| Text | Warm and concise |

## Accessibility Style

Prefer:
- short lines

## Judgment Style

| Situation | Rule |
|---|---|
| Uncertainty | Say what needs to be checked |
""",
        encoding="utf-8",
    )

    guidance = load_spark_voice_guidance(tmp_path, "sweta")

    assert guidance.voice_markers == ("Warm", "Clear")
    assert guidance.recurring_phrases == ("sounds good", "let me check")
    assert guidance.avoid_markers == ("Robotic",)
    assert guidance.channel_style["Text"] == "Warm and concise"
