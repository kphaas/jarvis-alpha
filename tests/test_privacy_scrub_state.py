from __future__ import annotations

from uuid import uuid4

import pytest

from brain.agents.privacy_scrub.state import (
    count_targets,
    get_target,
    insert_case_draft,
    insert_draft_action,
    list_targets,
    refresh_targets_cache,
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
