from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260618_234500_memory_consolidation_expired_proposal_cleanup.sql"
)
ROLLBACK = (
    REPO_ROOT
    / "brain"
    / "db"
    / "rollbacks"
    / "20260618_234500_memory_consolidation_expired_proposal_cleanup_rollback.sql"
)
SERVICE = REPO_ROOT / "brain" / "services" / "memory_consolidation_proposals.py"
MEMORY_TELEMETRY = REPO_ROOT / "brain" / "memory" / "memory.py"


def test_expired_proposal_cleanup_is_secdef_and_releases_holds() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert (
        "CREATE OR REPLACE FUNCTION public.expire_stale_memory_consolidation_proposals"
        in source
    )
    assert "SECURITY DEFINER" in source
    assert "PERFORM set_config('rls.role', 'platform_admin', true)" in source
    assert "q.status IN ('expired', 'denied', 'executed')" in source
    assert "q.expires_at <= NOW()" in source
    assert "status = 'stale'" in source
    assert "consolidation_hold = false" in source
    assert "SELECT public.expire_stale_memory_consolidation_proposals();" in source


def test_expired_proposal_cleanup_service_runs_before_upsert() -> None:
    source = SERVICE.read_text(encoding="utf-8")

    assert "await expire_stale_memory_consolidation_proposals(conn)" in source
    assert source.index("await expire_stale_memory_consolidation_proposals(conn)") < (
        source.index("INSERT INTO public.alpha_memory_consolidation_proposals")
    )


def test_memory_telemetry_counts_expired_approval_tokens_as_mismatch() -> None:
    source = MEMORY_TELEMETRY.read_text(encoding="utf-8")

    assert "dream_approval_mismatch_count" in source
    assert "q.expires_at IS NULL" in source
    assert "q.expires_at <= now()" in source


def test_expired_proposal_cleanup_rollback_drops_function_only() -> None:
    source = ROLLBACK.read_text(encoding="utf-8")

    assert (
        "DROP FUNCTION IF EXISTS public.expire_stale_memory_consolidation_proposals"
        in source
    )
    assert "UPDATE public.alpha_memory_consolidation_proposals" not in source
