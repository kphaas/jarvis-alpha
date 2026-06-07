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
) -> None:
    vault_root = _write_vault(tmp_path)
    fake_client = FakeBodyClient()

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
async def test_imessage_draft_uses_llm_context_without_exposing_thread_text(
    tmp_path: Path,
) -> None:
    vault_root = _write_vault(tmp_path)
    fake_client = FakeBodyClient()
    calls: list[dict[str, object]] = []

    async def fake_llm_call(**kwargs):
        calls.append(kwargs)
        return "Fair enough, I am on it and will come back with a clear answer."

    proposal = await drafts.create_imessage_draft_proposal(
        vault_root=vault_root,
        principal_id="ken",
        reply_goal="Tell her I am on it",
        max_context_messages=10,
        bluebubbles_client=fake_client,
        approved_chat_guid="approved-chat-guid",
        llm_call=fake_llm_call,
    )

    payload = proposal.to_payload()
    assert payload["draft_engine"] == "gateway_llm"
    assert payload["draft_text"].startswith("Fair enough")
    assert "llm_generated" in payload["warnings"]
    assert "private inbound body" not in json.dumps(payload).lower()
    assert len(calls) == 1
    llm_message = str(calls[0]["user_message"])
    assert "private inbound body" in llm_message
    assert "approved-chat-guid" not in json.dumps(calls).lower()


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
