from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from brain.services.bluebubbles_client import BlueBubblesMessageBody
from brain.services import spark_imessage_drafts as drafts


class FakeBodyClient:
    def __init__(self, *, sensitive: bool = False) -> None:
        self.calls: list[tuple[str, int]] = []
        self.sensitive = sensitive

    async def approved_messages_for_chat(
        self,
        *,
        chat_guid: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[BlueBubblesMessageBody, ...]:
        assert offset == 0
        self.calls.append((chat_guid, limit))
        inbound = (
            "We need to talk to the lawyer about court custody."
            if self.sensitive
            else "private inbound body with sensitive details"
        )
        return (
            BlueBubblesMessageBody(
                message_ref_hash=hashlib.sha256(b"inbound-1").hexdigest(),
                is_from_me=False,
                body_text=inbound,
            ),
            BlueBubblesMessageBody(
                message_ref_hash=hashlib.sha256(b"sent-1").hexdigest(),
                is_from_me=True,
                body_text="Ken sent body that stays runtime-only here",
            ),
        )


@pytest.mark.asyncio
async def test_imessage_draft_uses_runtime_context_without_exposing_thread_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault_root = _write_vault(tmp_path)
    fake_client = FakeBodyClient()
    monkeypatch.setenv(drafts.SPARK_DRAFT_LLM_ENABLED_ENV, "false")

    proposal = await drafts.create_imessage_draft_proposal(
        vault_root=vault_root,
        principal_id="ken",
        reply_goal="Tell her I am on it",
        max_context_messages=10,
        bluebubbles_client=fake_client,
        approved_chat_guid="approved-chat-guid",
    )

    payload = proposal.to_payload()
    serialized = json.dumps(payload).lower()
    assert payload["draft_text"] == "Tell her I am on it."
    assert payload["can_send"] is False
    assert payload["requires_human_approval"] is True
    assert payload["body_access"] is True
    assert payload["durable_storage_allowed"] is False
    assert payload["context_messages_read"] == 2
    assert payload["principal_sent_messages"] == 1
    assert payload["runtime_context_messages"] == 1
    assert payload["context_preview"] == []
    assert payload["personality_memory_preview"] == []
    assert fake_client.calls == [("approved-chat-guid", 10)]
    for forbidden in (
        "private inbound body",
        "ken sent body",
        "sensitive details",
        "approved-chat-guid",
        "relationship-thread-label",
    ):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_imessage_draft_can_return_runtime_context_preview_when_requested(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault_root = _write_vault(tmp_path)
    fake_client = FakeBodyClient()
    monkeypatch.setenv(drafts.SPARK_DRAFT_LLM_ENABLED_ENV, "false")

    proposal = await drafts.create_imessage_draft_proposal(
        vault_root=vault_root,
        principal_id="ken",
        reply_goal="Tell her I am on it",
        max_context_messages=10,
        bluebubbles_client=fake_client,
        approved_chat_guid="approved-chat-guid",
    )

    payload = proposal.to_payload(
        include_context_preview=True,
        context_preview_limit=10,
        personality_memory_preview=[
            {
                "kind": "style",
                "content": "Ken prefers short bullets for urgent decisions.",
                "source": "spark_approved",
                "evidence_ref_hash": "memory-hash",
            }
        ],
    )

    assert payload["context_preview"] == [
        {
            "index": 1,
            "speaker": "Other",
            "is_from_me": False,
            "message_ref_hash": hashlib.sha256(b"inbound-1").hexdigest(),
            "body_text": "private inbound body with sensitive details",
        },
        {
            "index": 2,
            "speaker": "Ken",
            "is_from_me": True,
            "message_ref_hash": hashlib.sha256(b"sent-1").hexdigest(),
            "body_text": "Ken sent body that stays runtime-only here",
        },
    ]
    assert payload["personality_memory_preview"] == [
        {
            "kind": "style",
            "content": "Ken prefers short bullets for urgent decisions.",
            "source": "spark_approved",
            "evidence_ref_hash": "memory-hash",
        }
    ]


@pytest.mark.asyncio
async def test_imessage_draft_uses_llm_context_without_exposing_thread_text(
    tmp_path: Path,
) -> None:
    vault_root = _write_vault(tmp_path)
    fake_client = FakeBodyClient()
    calls: list[dict[str, object]] = []

    async def fake_llm_call(**kwargs):
        calls.append(kwargs)
        return "Fair enough, I am on it and will see what actually makes sense."

    proposal = await drafts.create_imessage_draft_proposal(
        vault_root=vault_root,
        principal_id="ken",
        reply_goal="Tell her I am on it",
        max_context_messages=10,
        bluebubbles_client=fake_client,
        approved_chat_guid="approved-chat-guid",
        personality_memory_rows=[
            {
                "kind": "relationship",
                "content": "Sweta: partner; default hybrid_review; approval required True.",
            },
            {
                "kind": "boundary",
                "content": "relationship topics require Spark review before action.",
            },
        ],
        llm_call=fake_llm_call,
    )

    payload = proposal.to_payload()
    assert payload["draft_engine"] == "gateway_llm"
    assert payload["draft_text"].startswith("Fair enough")
    assert "llm_generated" in payload["warnings"]
    assert "private inbound body" not in json.dumps(payload).lower()
    assert len(calls) == 1
    system_prompt = str(calls[0]["system_prompt"])
    assert "Ken text-message calibration" in system_prompt
    assert "talk through the trade-offs" in system_prompt
    assert "what actually makes sense" in system_prompt
    assert "Auto operating context" in system_prompt
    assert "Surface the next real blocker" in system_prompt
    assert "Principal voice files win" in system_prompt
    assert "Approved Spark personality memory" in system_prompt
    assert "Sweta is Ken's partner." in system_prompt
    assert "default hybrid_review" not in system_prompt
    assert "approval required" not in system_prompt
    assert "require Spark review" not in system_prompt
    assert "Never mention memory, sensitivity labels" in system_prompt
    llm_message = str(calls[0]["user_message"])
    assert "private inbound body" in llm_message
    assert "approved-chat-guid" not in json.dumps(calls).lower()
    assert "surface the next real blocker" not in json.dumps(payload).lower()
    assert "sweta: partner" not in json.dumps(payload).lower()


@pytest.mark.asyncio
async def test_imessage_draft_blocks_detected_sensitive_topics_before_llm(
    tmp_path: Path,
) -> None:
    vault_root = _write_vault(tmp_path)
    fake_client = FakeBodyClient(sensitive=True)
    called = False

    async def fake_llm_call(**kwargs):
        nonlocal called
        called = True
        return "Should not run"

    with pytest.raises(drafts.SparkDraftPolicyError, match="sensitivity_blocked"):
        await drafts.create_imessage_draft_proposal(
            vault_root=vault_root,
            principal_id="ken",
            max_context_messages=10,
            bluebubbles_client=fake_client,
            approved_chat_guid="approved-chat-guid",
            llm_call=fake_llm_call,
        )

    assert fake_client.calls == [("approved-chat-guid", 10)]
    assert called is False


@pytest.mark.asyncio
async def test_imessage_draft_denies_relationship_thread_without_specific_approval(
    tmp_path: Path,
) -> None:
    vault_root = _write_vault(
        tmp_path,
        relationship_specific_approval_granted="no",
    )
    fake_client = FakeBodyClient()

    with pytest.raises(drafts.SparkDraftPolicyError, match="relationship"):
        await drafts.create_imessage_draft_proposal(
            vault_root=vault_root,
            principal_id="ken",
            max_context_messages=10,
            bluebubbles_client=fake_client,
            approved_chat_guid="approved-chat-guid",
        )

    assert fake_client.calls == []


@pytest.mark.asyncio
async def test_imessage_draft_requires_runtime_chat_guid_before_body_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault_root = _write_vault(tmp_path)
    fake_client = FakeBodyClient()
    monkeypatch.delenv(drafts.APPROVED_CHAT_GUID_ENV, raising=False)
    monkeypatch.delenv(
        "SPARK_IMESSAGE_APPROVED_CHAT_GUID_KEN_IMESSAGE_APPROVED_20260605_001",
        raising=False,
    )
    monkeypatch.setattr(
        drafts,
        "get_secret",
        lambda name: (_ for _ in ()).throw(KeyError(name)),
    )

    with pytest.raises(drafts.SparkDraftConfigError, match="chat GUID"):
        await drafts.create_imessage_draft_proposal(
            vault_root=vault_root,
            principal_id="ken",
            max_context_messages=10,
            bluebubbles_client=fake_client,
        )

    assert fake_client.calls == []


@pytest.mark.asyncio
async def test_imessage_draft_requires_auto_context_before_body_read(
    tmp_path: Path,
) -> None:
    vault_root = _write_vault(tmp_path, include_auto=False)
    fake_client = FakeBodyClient()

    with pytest.raises(drafts.SparkDraftConfigError, match="auto_spark_context"):
        await drafts.create_imessage_draft_proposal(
            vault_root=vault_root,
            principal_id="ken",
            max_context_messages=10,
            bluebubbles_client=fake_client,
            approved_chat_guid="approved-chat-guid",
        )

    assert fake_client.calls == []


@pytest.mark.asyncio
async def test_imessage_draft_uses_edited_draft_override(tmp_path: Path) -> None:
    vault_root = _write_vault(tmp_path)
    fake_client = FakeBodyClient()

    proposal = await drafts.create_imessage_draft_proposal(
        vault_root=vault_root,
        principal_id="ken",
        reply_goal="Tell her I am on it",
        draft_text_override="Edited text from review UI",
        bluebubbles_client=fake_client,
        approved_chat_guid="approved-chat-guid",
    )

    assert proposal.draft_text == "Edited text from review UI"
    assert fake_client.calls == [("approved-chat-guid", 20)]


def _write_vault(
    tmp_path: Path,
    *,
    relationship_specific_approval_granted: str = "yes",
    include_auto: bool = True,
) -> Path:
    principal_root = tmp_path / "spark" / "principals" / "ken"
    approvals = principal_root / "corpus_approvals"
    approvals.mkdir(parents=True)
    (principal_root / "sources.yml").write_text(
        """
version: 0.1.0
principal: ken
approved_source_records:
  - id: ken-imessage-approved-20260605-001
    source: imessage
    record: spark/principals/ken/corpus_approvals/imessage.md
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
- Clear

Ken-approved recurring phrases:
- fair enough
- cheers

Avoid sounding:
- Robotic
- Rambling

## Channel Style

| Channel | Rule |
|---|---|
| Text | Less formal |
| Email | More formal |

## Text Message Calibration

Avoid robotic wrap-ups such as:
- talk through the trade-offs
- circle back with a clear answer

Prefer natural endings with a concrete next action Ken would actually say:
- Let me look at the numbers and we'll see what actually makes sense.

## Accessibility Style

Prefer:
- Bullets
- Short lines

## Judgment Style

| Situation | Rule |
|---|---|
| Uncertainty | Admit uncertainty |
""",
        encoding="utf-8",
    )
    if include_auto:
        _write_auto_context(tmp_path)
    (approvals / "imessage.md").write_text(
        f"""
# Corpus Approval: Ken iMessage One-To-One Thread

| Field | Value |
|---|---|
| Approval ID | ken-imessage-approved-20260605-001 |
| Principal | ken |
| Source | imessage |
| Source reference | relationship-thread-label: approved-one-to-one |
| Thread kind | one_to_one |
| Requested max messages | 200 |

| Flag | Value |
|---|---|
| Relationship-marked | yes |
| Relationship-specific approval granted | {relationship_specific_approval_granted} |
| Legal or custody content | block if detected |

- [x] Approved
""",
        encoding="utf-8",
    )
    return tmp_path


def _write_auto_context(root: Path) -> None:
    (root / "auto" / "interfaces").mkdir(parents=True)
    (root / "auto" / "context").mkdir(parents=True)
    (root / "04_delegation").mkdir(parents=True)
    (root / "auto" / "interfaces" / "spark_context.yml").write_text(
        """
version: 0.1.0
allowed_for:
  - spark-draft
read_sources:
  - auto/mission.md
  - auto/context/current_state.md
  - auto/context/open_loops.md
  - 04_delegation/delegation_policy.yml
rules:
  - "Use this context only to understand current priorities and boundaries."
  - "Do not copy Auto internal notes into outbound drafts."
  - "Do not expose hidden chain-of-thought, tool details, or internal review notes."
  - "Do not use sensitive context unless approved."
  - "Principal voice files win."
runtime_mode:
  spark_can_read: true
  spark_can_write: false
  durable_memory_writes: false
  outbound_send_allowed: false
""",
        encoding="utf-8",
    )
    (root / "auto" / "mission.md").write_text(
        """
# Auto Mission

## Primary Jobs

- Surface the next real blocker.
- Keep project state coherent.

## Operating Bias

- Be direct.
- Be evidence-led.
""",
        encoding="utf-8",
    )
    (root / "auto" / "context" / "current_state.md").write_text(
        """
# Current State

## Known Live Gates

- Spark must remain draft-first.
- External sends require approval.
""",
        encoding="utf-8",
    )
    (root / "auto" / "context" / "open_loops.md").write_text(
        """
# Open Loops

## Spark

- Wire Auto context into the draft prompt.
""",
        encoding="utf-8",
    )
    (root / "04_delegation" / "delegation_policy.yml").write_text(
        "# Delegation Policy\n\nversion: 0.1.0\n",
        encoding="utf-8",
    )
