from __future__ import annotations

from uuid import uuid4

import pytest

from brain.agents.privacy_scrub.state import (
    count_targets,
    enqueue_approval_request,
    get_case_draft,
    get_target,
    insert_case_draft,
    insert_draft_action,
    list_approved_privacy_actions,
    list_privacy_action_events_for_case,
    list_privacy_actions_for_case,
    list_targets,
    mark_approval_queue_actions_decided,
    mark_case_actions_awaiting_approval,
    reject_pending_case_actions,
    refresh_targets_cache,
    update_privacy_action_manual_disposition,
    update_privacy_action_verification,
    update_case_draft_status,
)
from brain.agents.privacy_scrub.targets import (
    Jurisdiction,
    OptOutMethod,
    Target,
    TargetCategory,
)


class FakeTargetCacheConnection:
    def __init__(self) -> None:
        self.executes: list[tuple[str, tuple[object, ...]]] = []
        self.fetchrows: list[tuple[str, tuple[object, ...]]] = []
        self.fetchvals: list[tuple[str, tuple[object, ...]]] = []
        self.transaction_entries = 0
        self.transaction_exits = 0
        self.fetchrow_result: dict[str, object] | None = None
        self.fetch_result: list[dict[str, object]] = []
        self.fetchval_result: int = 0

    def transaction(self) -> "FakeTargetCacheConnection":
        return self

    async def __aenter__(self) -> "FakeTargetCacheConnection":
        self.transaction_entries += 1
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.transaction_exits += 1

    async def execute(self, query: str, *args: object) -> None:
        self.executes.append((query, args))

    async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
        self.fetchrows.append((query, args))
        return self.fetchrow_result

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        self.fetchrows.append((query, args))
        return self.fetch_result

    async def fetchval(self, query: str, *args: object) -> int:
        self.fetchvals.append((query, args))
        return self.fetchval_result


class FakeDraftWriteConnection:
    def __init__(self) -> None:
        self.fetchrows: list[tuple[str, tuple[object, ...]]] = []
        self.fetches: list[tuple[str, tuple[object, ...]]] = []
        self.fetchvals: list[tuple[str, tuple[object, ...]]] = []
        self.queue_id = uuid4()

    async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
        self.fetchrows.append((query, args))
        if "INSERT INTO public.alpha_privacy_case_drafts" in query:
            return {
                "id": args[0],
                "subject_id": args[0],
                "created_by_user_id": args[1],
                "target_count": args[2],
                "status": "draft",
                "packet_payload_hash": args[4],
                "payload_key_version": args[5],
                "created_at": None,
                "updated_at": None,
            }
        if "UPDATE public.alpha_privacy_case_drafts" in query:
            return {
                "id": args[0],
                "subject_id": uuid4(),
                "created_by_user_id": "ken",
                "target_count": 1,
                "status": args[1],
                "packet_payload_hash": "sha256:" + "3" * 64,
                "payload_key_version": "payload-v1",
                "created_at": None,
                "updated_at": None,
            }
        if "FROM public.alpha_privacy_case_drafts" in query:
            return {
                "id": args[0],
                "subject_id": uuid4(),
                "created_by_user_id": "ken",
                "target_count": 2,
                "status": "submitted_for_approval",
                "packet_payload_hash": "sha256:" + "3" * 64,
                "payload_key_version": "payload-v1",
                "created_at": None,
                "updated_at": None,
            }
        if "WITH updated AS" in query and "manual_disposition_at = NOW()" in query:
            return _approved_action_row(
                action_id=args[0],
                status=args[1],
                manual_disposition=args[2],
                manual_disposition_by=args[3],
                manual_note_hash=args[5],
                evidence_payload_hash=args[7],
                workflow_payload_key_version=args[8],
            )
        if "WITH updated AS" in query and "manual_disposition = COALESCE" in query:
            return _approved_action_row(
                action_id=args[0],
                status=args[1],
                manual_disposition="handled",
                evidence_payload_hash=args[4],
                workflow_payload_key_version=args[5],
            )
        if "INSERT INTO public.alpha_privacy_actions" in query:
            return {
                "id": args[2],
                "subject_id": args[0],
                "target_id": args[1],
                "case_draft_id": args[2],
                "action_type": args[3],
                "approval_tier": args[4],
                "status": "pending",
                "draft_payload_hash": args[6],
                "payload_key_version": args[7],
                "created_at": None,
                "updated_at": None,
            }
        raise AssertionError(f"unexpected fetchrow query: {query}")

    async def fetch(self, query: str, *args: object) -> list[dict[str, object]]:
        self.fetches.append((query, args))
        if "e.id, e.action_id" in query:
            return [
                {
                    "id": uuid4(),
                    "action_id": uuid4(),
                    "case_draft_id": args[0],
                    "target_id": "spokeo",
                    "target_name": "Spokeo",
                    "event_type": "sent",
                    "actor": "ken",
                    "event_payload_hash": "sha256:" + "5" * 64,
                    "created_at": None,
                }
            ]
        if "FROM public.alpha_privacy_actions AS a" in query and (
            "approval_queue_id IS NOT NULL" in query or "a.case_draft_id = $1" in query
        ):
            return [_approved_action_row(status="approved")]
        if "SET status = $2" in query:
            status = str(args[1])
            case_draft_id = uuid4()
        else:
            status = "awaiting_approval" if "awaiting_approval" in query else "rejected"
            case_draft_id = args[0]
        return [
            {
                "id": uuid4(),
                "subject_id": uuid4(),
                "target_id": "spokeo",
                "case_draft_id": case_draft_id,
                "action_type": "draft",
                "approval_tier": "T2",
                "status": status,
                "draft_payload_hash": "sha256:" + "4" * 64,
                "payload_key_version": "payload-v1",
                "created_at": None,
                "updated_at": None,
            }
        ]

    async def fetchval(self, query: str, *args: object):
        self.fetchvals.append((query, args))
        return self.queue_id


def _approved_action_row(
    *,
    action_id: object | None = None,
    status: object = "approved",
    manual_disposition: object = None,
    manual_disposition_by: object = None,
    manual_note_hash: object = None,
    evidence_payload_hash: object = None,
    workflow_payload_key_version: object = None,
) -> dict[str, object]:
    return {
        "id": action_id or uuid4(),
        "subject_id": uuid4(),
        "target_id": "spokeo",
        "case_draft_id": uuid4(),
        "action_type": "draft",
        "approval_tier": "T2",
        "status": status,
        "approval_queue_id": uuid4(),
        "draft_payload_hash": "sha256:" + "4" * 64,
        "payload_key_version": "payload-v1",
        "manual_disposition": manual_disposition,
        "manual_disposition_at": None,
        "manual_disposition_by": manual_disposition_by,
        "manual_note_hash": manual_note_hash,
        "evidence_payload_hash": evidence_payload_hash,
        "workflow_payload_key_version": workflow_payload_key_version,
        "sent_at": None,
        "confirmed_at": None,
        "verification_due_at": None,
        "error_code": None,
        "error_digest": None,
        "target_name": "Spokeo",
        "target_category": "data_broker",
        "target_jurisdiction": "US_FEDERAL",
        "target_opt_out_method": "web_form",
        "target_avg_response_days": 5,
        "case_status": "submitted_for_approval",
        "case_created_at": None,
        "approved_at": None,
        "created_at": None,
        "updated_at": None,
    }


def _target() -> Target:
    return Target(
        id="rls_test_target",
        name="RLS Test Target",
        category=TargetCategory.DATA_BROKER,
        jurisdiction=Jurisdiction.US_FEDERAL,
        opt_out_method=OptOutMethod.WEB_FORM,
    )


@pytest.mark.asyncio
async def test_refresh_targets_cache_sets_platform_admin_rls_context() -> None:
    conn = FakeTargetCacheConnection()

    count = await refresh_targets_cache(conn, [_target()], source_label="test")  # type: ignore[arg-type]

    assert count == 1
    assert conn.transaction_entries == 1
    assert conn.transaction_exits == 1
    queries = [query for query, _args in conn.executes]
    assert queries[0] == "SELECT set_config('rls.role', 'platform_admin', true)"
    assert queries[1] == "DELETE FROM public.alpha_privacy_targets_cache"
    assert "INSERT INTO public.alpha_privacy_targets_cache" in queries[2]


@pytest.mark.asyncio
async def test_count_targets_sets_platform_admin_rls_context() -> None:
    conn = FakeTargetCacheConnection()
    conn.fetchval_result = 3

    count = await count_targets(conn)  # type: ignore[arg-type]

    assert count == 3
    assert conn.transaction_entries == 1
    assert conn.transaction_exits == 1
    assert conn.executes == [
        ("SELECT set_config('rls.role', 'platform_admin', true)", ())
    ]
    assert conn.fetchvals[0][0] == (
        "SELECT COUNT(*) FROM public.alpha_privacy_targets_cache"
    )


@pytest.mark.asyncio
async def test_get_target_sets_platform_admin_rls_context() -> None:
    conn = FakeTargetCacheConnection()
    conn.fetchrow_result = {"id": "target_1", "name": "Target"}

    target = await get_target(conn, "target_1")  # type: ignore[arg-type]

    assert target == {"id": "target_1", "name": "Target"}
    assert conn.transaction_entries == 1
    assert conn.transaction_exits == 1
    assert conn.executes == [
        ("SELECT set_config('rls.role', 'platform_admin', true)", ())
    ]
    query, args = conn.fetchrows[0]
    assert "FROM public.alpha_privacy_targets_cache" in query
    assert args == ("target_1",)


@pytest.mark.asyncio
async def test_list_targets_sets_platform_admin_rls_context() -> None:
    conn = FakeTargetCacheConnection()
    conn.fetch_result = [{"id": "target_1", "name": "Target"}]

    targets = await list_targets(conn)  # type: ignore[arg-type]

    assert targets == [{"id": "target_1", "name": "Target"}]
    assert conn.transaction_entries == 1
    assert conn.transaction_exits == 1
    assert conn.executes == [
        ("SELECT set_config('rls.role', 'platform_admin', true)", ())
    ]
    query, args = conn.fetchrows[0]
    assert "FROM public.alpha_privacy_targets_cache" in query
    assert "ORDER BY category, jurisdiction, name, id" in query
    assert args == ()


@pytest.mark.asyncio
async def test_insert_case_draft_writes_encrypted_packet_payload() -> None:
    conn = FakeDraftWriteConnection()
    subject_id = uuid4()

    case = await insert_case_draft(
        conn,  # type: ignore[arg-type]
        subject_id=subject_id,
        created_by_user_id="ken",
        target_count=2,
        packet_payload_ciphertext=b"ciphertext",
        packet_payload_hash="sha256:" + "1" * 64,
        payload_key_version="payload-v1",
    )

    query, args = conn.fetchrows[0]
    assert "INSERT INTO public.alpha_privacy_case_drafts" in query
    assert "packet_payload_ciphertext" in query
    assert args[0] == subject_id
    assert args[3] == b"ciphertext"
    assert case.subject_id == subject_id
    assert case.target_count == 2


@pytest.mark.asyncio
async def test_insert_draft_action_is_limited_to_draft_action_type() -> None:
    conn = FakeDraftWriteConnection()
    subject_id = uuid4()
    case_id = uuid4()

    action = await insert_draft_action(
        conn,  # type: ignore[arg-type]
        subject_id=subject_id,
        target_id="spokeo",
        case_draft_id=case_id,
        action_type="draft",
        approval_tier="T2",
        draft_payload_ciphertext=b"ciphertext",
        draft_payload_hash="sha256:" + "2" * 64,
        payload_key_version="payload-v1",
    )

    query, args = conn.fetchrows[0]
    assert "INSERT INTO public.alpha_privacy_actions" in query
    assert "case_draft_id" in query
    assert args[3] == "draft"
    assert action.case_draft_id == case_id
    assert action.status == "pending"

    with pytest.raises(ValueError, match="draft"):
        await insert_draft_action(
            conn,  # type: ignore[arg-type]
            subject_id=subject_id,
            target_id="spokeo",
            case_draft_id=case_id,
            action_type="send_opt_out",
            approval_tier="T4",
            draft_payload_ciphertext=b"ciphertext",
            draft_payload_hash="sha256:" + "3" * 64,
            payload_key_version="payload-v1",
        )


@pytest.mark.asyncio
async def test_enqueue_approval_request_uses_secdef_wrapper() -> None:
    conn = FakeDraftWriteConnection()

    queue_id = await enqueue_approval_request(
        conn,  # type: ignore[arg-type]
        action_classes=("privacy_draft_handoff", "security_write"),
        risk_tier="T4",
        actor_sub="ken",
        actor_type="user",
        description="Privacy case draft approval handoff",
        parameters_hash="a" * 64,
        nonce="nonce",
    )

    query, args = conn.fetchvals[0]
    assert queue_id == conn.queue_id
    assert "public.enqueue_approval_request" in query
    assert args[0] == ["privacy_draft_handoff", "security_write"]
    assert args[1] == "T4"
    assert args[2] == "ken"


@pytest.mark.asyncio
async def test_update_case_draft_status_checks_expected_status() -> None:
    conn = FakeDraftWriteConnection()
    case_id = uuid4()

    result = await update_case_draft_status(
        conn,  # type: ignore[arg-type]
        case_draft_id=case_id,
        status="submitted_for_approval",
        expected_statuses=("draft",),
    )

    query, args = conn.fetchrows[0]
    assert result is not None
    assert result.id == case_id
    assert result.status == "submitted_for_approval"
    assert "status = ANY($3::text[])" in query
    assert args[2] == ["draft"]


@pytest.mark.asyncio
async def test_mark_case_actions_awaiting_approval_links_queue() -> None:
    conn = FakeDraftWriteConnection()
    case_id = uuid4()
    queue_id = uuid4()

    actions = await mark_case_actions_awaiting_approval(
        conn,  # type: ignore[arg-type]
        case_draft_id=case_id,
        approval_queue_id=queue_id,
    )

    query, args = conn.fetches[0]
    assert actions[0].status == "awaiting_approval"
    assert "approval_queue_id = $2" in query
    assert args == (case_id, queue_id)


@pytest.mark.asyncio
async def test_mark_approval_queue_actions_decided_sets_final_status() -> None:
    conn = FakeDraftWriteConnection()
    queue_id = uuid4()

    actions = await mark_approval_queue_actions_decided(
        conn,  # type: ignore[arg-type]
        approval_queue_id=queue_id,
        status="approved",
    )

    query, args = conn.fetches[0]
    assert actions[0].status == "approved"
    assert "WHERE approval_queue_id = $1" in query
    assert "AND status = 'awaiting_approval'" in query
    assert args == (queue_id, "approved")


@pytest.mark.asyncio
async def test_list_approved_privacy_actions_filters_ready_rows() -> None:
    conn = FakeDraftWriteConnection()

    actions = await list_approved_privacy_actions(conn, limit=12)  # type: ignore[arg-type]

    query, args = conn.fetches[0]
    assert actions[0].status == "approved"
    assert actions[0].target_name == "Spokeo"
    assert actions[0].case_status == "submitted_for_approval"
    assert "FROM public.alpha_privacy_actions AS a" in query
    assert "JOIN public.alpha_privacy_targets_cache AS t" in query
    assert "a.status IN ('approved', 'sent', 'confirmed', 'failed')" in query
    assert "approval_queue_id IS NOT NULL" in query
    assert "draft_payload_ciphertext" not in query
    assert args == (12,)


@pytest.mark.asyncio
async def test_update_privacy_action_manual_disposition_records_encrypted_hashes() -> (
    None
):
    conn = FakeDraftWriteConnection()
    action_id = uuid4()

    action = await update_privacy_action_manual_disposition(
        conn,  # type: ignore[arg-type]
        action_id=action_id,
        disposition="handled",
        actor="ken",
        manual_note_ciphertext=b"note-ciphertext",
        manual_note_hash="sha256:" + "6" * 64,
        evidence_payload_ciphertext=b"evidence-ciphertext",
        evidence_payload_hash="sha256:" + "7" * 64,
        workflow_payload_key_version="payload-v2",
    )

    assert action is not None
    query, args = conn.fetchrows[0]
    assert action.id == action_id
    assert action.status == "sent"
    assert action.manual_disposition == "handled"
    assert action.manual_note_hash == "sha256:" + "6" * 64
    assert action.evidence_payload_hash == "sha256:" + "7" * 64
    assert "manual_note_ciphertext = $5" in query
    assert "evidence_payload_ciphertext = $7" in query
    assert "approval_queue_id IS NOT NULL" in query
    assert "$10::timestamptz" in query
    assert args[0] == action_id
    assert args[1] == "sent"
    assert args[8] == "payload-v2"


@pytest.mark.asyncio
async def test_update_privacy_action_verification_sets_confirmed_status() -> None:
    conn = FakeDraftWriteConnection()
    action_id = uuid4()

    action = await update_privacy_action_verification(
        conn,  # type: ignore[arg-type]
        action_id=action_id,
        outcome="confirmed",
        actor="ken",
        evidence_payload_hash="sha256:" + "8" * 64,
        workflow_payload_key_version="payload-v2",
    )

    assert action is not None
    query, args = conn.fetchrows[0]
    assert action.id == action_id
    assert action.status == "confirmed"
    assert action.manual_disposition == "handled"
    assert "confirmed_at = CASE" in query
    assert "verification_due_at = CASE" in query
    assert "$7::timestamptz" in query
    assert "NULL::timestamptz" in query
    assert args[0] == action_id
    assert args[1] == "confirmed"
    assert args[5] == "payload-v2"


@pytest.mark.asyncio
async def test_case_workflow_readers_exclude_ciphertexts() -> None:
    conn = FakeDraftWriteConnection()
    case_id = uuid4()

    case = await get_case_draft(conn, case_id)  # type: ignore[arg-type]
    actions = await list_privacy_actions_for_case(  # type: ignore[arg-type]
        conn,
        case_draft_id=case_id,
    )
    events = await list_privacy_action_events_for_case(  # type: ignore[arg-type]
        conn,
        case_draft_id=case_id,
    )

    assert case is not None
    assert actions[0].target_name == "Spokeo"
    assert events[0].event_type == "sent"
    action_query = conn.fetches[0][0]
    event_query = conn.fetches[1][0]
    assert "manual_note_ciphertext" not in action_query
    assert "evidence_payload_ciphertext" not in action_query
    assert "event_payload_ciphertext" not in event_query


@pytest.mark.asyncio
async def test_reject_pending_case_actions_marks_archive_rejections() -> None:
    conn = FakeDraftWriteConnection()
    case_id = uuid4()

    actions = await reject_pending_case_actions(
        conn,  # type: ignore[arg-type]
        case_draft_id=case_id,
    )

    query, args = conn.fetches[0]
    assert actions[0].status == "rejected"
    assert "SET status = 'rejected'" in query
    assert args == (case_id,)
