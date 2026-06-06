from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from brain.agents.privacy_scrub.crypto import PrivacyCrypto, PrivacyCryptoConfig
from brain.agents.privacy_scrub.state import (
    StoredApprovedPrivacyAction,
    StoredCaseDraft,
)
from brain.agents.privacy_scrub.workflow import (
    PrivacyActionWorkflowRepository,
    PrivacyActionWorkflowTransitionError,
)
import brain.agents.privacy_scrub.workflow as workflow


class FakeWorkflowConnection:
    def __init__(self) -> None:
        self.transaction_entries = 0
        self.transaction_exits = 0

    def transaction(self) -> "FakeWorkflowConnection":
        return self

    async def __aenter__(self) -> "FakeWorkflowConnection":
        self.transaction_entries += 1
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.transaction_exits += 1


def _crypto() -> PrivacyCrypto:
    return PrivacyCrypto(
        PrivacyCryptoConfig(
            digest_key="test-digest",
            digest_key_version="digest-v1",
            payload_key="test-payload",
            payload_key_version="payload-v1",
        )
    )


def _approved_action(
    *,
    action_id: UUID,
    case_id: UUID,
) -> StoredApprovedPrivacyAction:
    return StoredApprovedPrivacyAction(
        id=action_id,
        subject_id=uuid4(),
        target_id="spokeo",
        case_draft_id=case_id,
        action_type="draft",
        approval_tier="T2",
        status="confirmed",
        approval_queue_id=uuid4(),
        draft_payload_hash="sha256:" + "1" * 64,
        payload_key_version="payload-v1",
        target_name="Spokeo",
        target_category="data_broker",
        target_jurisdiction="US_FEDERAL",
        target_opt_out_method="web_form",
        target_avg_response_days=5,
        case_status="submitted_for_approval",
        case_created_at=None,
        approved_at=None,
    )


def _completed_case(case_id: UUID) -> StoredCaseDraft:
    return StoredCaseDraft(
        id=case_id,
        subject_id=uuid4(),
        created_by_user_id="ken",
        target_count=1,
        status="completed",
        packet_payload_hash="sha256:" + "2" * 64,
        payload_key_version="payload-v1",
    )


@pytest.mark.asyncio
async def test_record_verification_returns_completed_case_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeWorkflowConnection()
    action_id = uuid4()
    case_id = uuid4()
    calls: dict[str, object] = {}

    async def fake_update_privacy_action_verification(
        conn_arg: object,
        **kwargs: object,
    ) -> StoredApprovedPrivacyAction:
        calls["verification"] = kwargs
        assert conn_arg is conn
        return _approved_action(action_id=action_id, case_id=case_id)

    async def fake_append_action_event(conn_arg: object, **kwargs: object) -> None:
        calls["event"] = kwargs
        assert conn_arg is conn

    async def fake_mark_case_draft_completed_if_terminal(
        conn_arg: object,
        **kwargs: object,
    ) -> StoredCaseDraft:
        calls["completed"] = kwargs
        assert conn_arg is conn
        return _completed_case(case_id)

    monkeypatch.setattr(
        workflow,
        "update_privacy_action_verification",
        fake_update_privacy_action_verification,
    )
    monkeypatch.setattr(workflow, "append_action_event", fake_append_action_event)
    monkeypatch.setattr(
        workflow,
        "mark_case_draft_completed_if_terminal",
        fake_mark_case_draft_completed_if_terminal,
    )

    result = await PrivacyActionWorkflowRepository(
        conn,  # type: ignore[arg-type]
        _crypto(),
    ).record_verification(
        action_id=action_id,
        actor="ken",
        outcome="confirmed",
        evidence_reference="manual-ticket-1",
    )

    assert result.event_type == "confirmed"
    assert result.action.case_status == "completed"
    verification_call = calls["verification"]
    assert isinstance(verification_call, dict)
    assert verification_call["action_id"] == action_id
    assert verification_call["outcome"] == "confirmed"
    assert verification_call["actor"] == "ken"
    assert isinstance(verification_call["evidence_payload_ciphertext"], bytes)
    assert str(verification_call["evidence_payload_hash"]).startswith("sha256:")
    assert verification_call["workflow_payload_key_version"] == "payload-v1"
    assert verification_call["verification_due_at"] is None
    assert calls["completed"] == {"case_draft_id": case_id}
    assert conn.transaction_entries == 1
    assert conn.transaction_exits == 1


@pytest.mark.asyncio
async def test_record_manual_disposition_deferred_requires_due_date() -> None:
    conn = FakeWorkflowConnection()

    with pytest.raises(
        PrivacyActionWorkflowTransitionError,
        match="deferral requires a due date",
    ):
        await PrivacyActionWorkflowRepository(
            conn,  # type: ignore[arg-type]
            _crypto(),
        ).record_manual_disposition(
            action_id=uuid4(),
            actor="ken",
            disposition="deferred",
        )

    assert conn.transaction_entries == 0
    assert conn.transaction_exits == 0


@pytest.mark.asyncio
async def test_record_verification_needs_followup_requires_due_date() -> None:
    conn = FakeWorkflowConnection()

    with pytest.raises(
        PrivacyActionWorkflowTransitionError,
        match="follow-up requires a due date",
    ):
        await PrivacyActionWorkflowRepository(
            conn,  # type: ignore[arg-type]
            _crypto(),
        ).record_verification(
            action_id=uuid4(),
            actor="ken",
            outcome="needs_followup",
        )

    assert conn.transaction_entries == 0
    assert conn.transaction_exits == 0
