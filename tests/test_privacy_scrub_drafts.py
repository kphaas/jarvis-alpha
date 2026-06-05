from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from brain.agents.privacy_scrub import drafts
from brain.agents.privacy_scrub.crypto import PrivacyCrypto, PrivacyCryptoConfig
from brain.agents.privacy_scrub.drafts import (
    PrivacyCaseDraftRepository,
    PrivacyDraftError,
)
from brain.agents.privacy_scrub.identity import IdentityTuple, TupleType
from brain.agents.privacy_scrub.state import (
    StoredCaseDraft,
    StoredDraftAction,
    StoredSubject,
)
from brain.agents.privacy_scrub.subjects import Role, SubjectStatus


class FakeDraftConnection:
    def __init__(self) -> None:
        self.transaction_entries = 0
        self.transaction_exits = 0

    def transaction(self) -> "FakeDraftConnection":
        return self

    async def __aenter__(self) -> "FakeDraftConnection":
        self.transaction_entries += 1
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.transaction_exits += 1


def _crypto() -> PrivacyCrypto:
    return PrivacyCrypto(
        PrivacyCryptoConfig(
            digest_key="draft-digest-key",
            digest_key_version="digest-v1",
            payload_key="draft-payload-key",
            payload_key_version="payload-v1",
        )
    )


def _subject(subject_id, role: Role = Role.ADULT) -> StoredSubject:
    return StoredSubject(
        id=subject_id,
        user_id="ken",
        display_label_digest="hmac-sha256:" + "1" * 64,
        role=role,
        guardian_user_id="ken" if role == Role.MINOR else None,
        jurisdiction="US_GA",
        status=SubjectStatus.ACTIVE,
        subject_payload_hash="sha256:" + "2" * 64,
        subject_payload_key_version="payload-v1",
    )


def _target_row(target_id: str) -> dict[str, object]:
    if target_id == "ga_fulton_superior":
        return {
            "id": "ga_fulton_superior",
            "name": "Fulton County Superior Court (GA)",
            "category": "public_record",
            "jurisdiction": "US_GA",
            "opt_out_method": "court_motion",
            "opt_out_url": None,
            "contact_email": None,
            "supports_minors": False,
            "requires_sensitive_payload": False,
            "requires_identity_document": False,
            "avg_response_days": None,
            "last_verified": None,
            "notes": None,
        }
    return {
        "id": "spokeo",
        "name": "Spokeo",
        "category": "data_broker",
        "jurisdiction": "US_FEDERAL",
        "opt_out_method": "web_form",
        "opt_out_url": "https://example.test/optout",
        "contact_email": None,
        "supports_minors": False,
        "requires_sensitive_payload": False,
        "requires_identity_document": False,
        "avg_response_days": 5,
        "last_verified": None,
        "notes": "local registry metadata",
    }


@pytest.mark.asyncio
async def test_case_draft_repository_creates_encrypted_actions(monkeypatch) -> None:
    subject_id = uuid4()
    case_id = uuid4()
    action_ids = [uuid4(), uuid4()]
    calls = SimpleNamespace(case_insert=None, actions=[], events=[])

    async def fake_get_subject(conn, subject_id_arg):
        assert subject_id_arg == subject_id
        return _subject(subject_id)

    async def fake_list_identity_tuples(conn, subject_id_arg, active_only=True):
        assert subject_id_arg == subject_id
        assert active_only is True
        return [
            IdentityTuple(
                id=None,
                subject_id=subject_id,
                tuple_type=TupleType.FULL_NAME,
                digest="hmac-sha256:" + "3" * 64,
                key_version="digest-v1",
            ),
            IdentityTuple(
                id=None,
                subject_id=subject_id,
                tuple_type=TupleType.EMAIL,
                digest="hmac-sha256:" + "4" * 64,
                key_version="digest-v1",
            ),
        ]

    async def fake_get_target(conn, target_id):
        return _target_row(target_id)

    async def fake_insert_case_draft(conn, **kwargs):
        calls.case_insert = kwargs
        return StoredCaseDraft(
            id=case_id,
            subject_id=kwargs["subject_id"],
            created_by_user_id=kwargs["created_by_user_id"],
            target_count=kwargs["target_count"],
            status="draft",
            packet_payload_hash=kwargs["packet_payload_hash"],
            payload_key_version=kwargs["payload_key_version"],
        )

    async def fake_insert_draft_action(conn, **kwargs):
        index = len(calls.actions)
        calls.actions.append(kwargs)
        return StoredDraftAction(
            id=action_ids[index],
            subject_id=kwargs["subject_id"],
            target_id=kwargs["target_id"],
            case_draft_id=kwargs["case_draft_id"],
            action_type=kwargs["action_type"],
            approval_tier=kwargs["approval_tier"],
            status="pending",
            draft_payload_hash=kwargs["draft_payload_hash"],
            payload_key_version=kwargs["payload_key_version"],
        )

    async def fake_append_action_event(conn, **kwargs):
        calls.events.append(kwargs)
        return uuid4()

    monkeypatch.setattr(drafts, "get_subject", fake_get_subject)
    monkeypatch.setattr(drafts, "list_identity_tuples", fake_list_identity_tuples)
    monkeypatch.setattr(drafts, "get_target", fake_get_target)
    monkeypatch.setattr(drafts, "insert_case_draft", fake_insert_case_draft)
    monkeypatch.setattr(drafts, "insert_draft_action", fake_insert_draft_action)
    monkeypatch.setattr(drafts, "append_action_event", fake_append_action_event)

    conn = FakeDraftConnection()
    result = await PrivacyCaseDraftRepository(
        conn,  # type: ignore[arg-type]
        _crypto(),
    ).create_case_draft(
        user_id="ken",
        subject_id=subject_id,
        target_ids=("spokeo", "ga_fulton_superior"),
    )

    assert result.case_draft.id == case_id
    assert result.case_draft.target_count == 2
    assert [packet.target_id for packet in result.review_packets] == [
        "spokeo",
        "ga_fulton_superior",
    ]
    assert result.review_packets[0].approval_tier == "T2"
    assert result.review_packets[1].approval_tier == "T4"
    assert result.actions[0].approval_tier == "T2"
    assert result.actions[1].approval_tier == "T4"
    assert calls.case_insert["payload_key_version"] == "payload-v1"
    assert calls.case_insert["packet_payload_hash"].startswith("sha256:")
    assert b"Spokeo" not in calls.case_insert["packet_payload_ciphertext"]
    assert all(
        action["draft_payload_hash"].startswith("sha256:") for action in calls.actions
    )
    assert calls.events == [
        {"action_id": action_ids[0], "event_type": "created", "actor": "ken"},
        {"action_id": action_ids[1], "event_type": "created", "actor": "ken"},
    ]
    assert conn.transaction_entries == 1
    assert conn.transaction_exits == 1


@pytest.mark.asyncio
async def test_case_draft_repository_rejects_duplicate_targets_before_db(
    monkeypatch,
) -> None:
    async def fail_get_subject(conn, subject_id):
        raise AssertionError("subject lookup should not run for duplicate targets")

    monkeypatch.setattr(drafts, "get_subject", fail_get_subject)

    with pytest.raises(PrivacyDraftError, match="unique"):
        await PrivacyCaseDraftRepository(
            FakeDraftConnection(),  # type: ignore[arg-type]
            _crypto(),
        ).create_case_draft(
            user_id="ken",
            subject_id=uuid4(),
            target_ids=("spokeo", "spokeo"),
        )


def test_drafts_module_has_no_outbound_imports_or_plaintext_logging() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "brain"
        / "agents"
        / "privacy_scrub"
        / "drafts.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "requests",
        "httpx",
        "smtplib",
        "selenium",
        "playwright",
        "print(",
        "send_opt_out",
    )

    for token in forbidden:
        assert token not in source
