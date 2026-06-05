from __future__ import annotations

import pytest

from brain.agents.privacy_scrub.state import (
    count_targets,
    get_target,
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

    async def fetchval(self, query: str, *args: object) -> int:
        self.fetchvals.append((query, args))
        return self.fetchval_result


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
