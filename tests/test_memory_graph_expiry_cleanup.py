from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260622_153000_memory_graph_expired_proposal_cleanup.sql"
)
ROLLBACK = (
    REPO_ROOT
    / "brain"
    / "db"
    / "rollbacks"
    / "20260622_153000_memory_graph_expired_proposal_cleanup_rollback.sql"
)


def test_graph_expired_proposal_cleanup_is_secdef_and_rejects_expired() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert (
        "CREATE OR REPLACE FUNCTION public.expire_stale_memory_graph_proposals"
        in source
    )
    assert "SECURITY DEFINER" in source
    assert "PERFORM set_config('rls.role', 'platform_admin', true)" in source
    assert "q.status IN ('expired', 'denied', 'executed')" in source
    assert "q.expires_at <= NOW()" in source
    assert "status = 'rejected'" in source
    assert "approval token expired or is no longer executable" in source
    assert "SELECT public.expire_stale_memory_graph_proposals();" in source
    assert "FROM public.alpha_memory_graph_proposals p" in source


def test_graph_expired_proposal_cleanup_rollback_drops_function_only() -> None:
    source = ROLLBACK.read_text(encoding="utf-8")

    assert (
        "DROP FUNCTION IF EXISTS public.expire_stale_memory_graph_proposals" in source
    )
    assert "UPDATE public.alpha_memory_graph_proposals" not in source
