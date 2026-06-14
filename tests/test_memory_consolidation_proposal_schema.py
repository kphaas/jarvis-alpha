from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260614_110000_memory_consolidation_proposals.sql"
)
ROLLBACK = (
    REPO_ROOT
    / "brain"
    / "db"
    / "rollbacks"
    / "20260614_110000_memory_consolidation_proposals_rollback.sql"
)


def test_memory_consolidation_schema_has_proposals_and_mandatory_ledger() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert (
        "CREATE TABLE IF NOT EXISTS public.alpha_memory_consolidation_proposals"
        in source
    )
    assert (
        "CREATE TABLE IF NOT EXISTS public.alpha_memory_consolidation_execution_ledger"
        in source
    )
    assert "proposal_id" in source
    assert "approval_queue_id" in source
    assert "evidence" in source
    assert "decision" in source
    assert "undo_path" in source
    assert "UNIQUE (proposal_id, operation)" in source


def test_memory_consolidation_schema_is_rls_forced_and_t5_oriented() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert (
        "ALTER TABLE public.alpha_memory_consolidation_proposals ENABLE ROW LEVEL SECURITY"
        in source
    )
    assert (
        "ALTER TABLE public.alpha_memory_consolidation_proposals FORCE ROW LEVEL SECURITY"
        in source
    )
    assert (
        "ALTER TABLE public.alpha_memory_consolidation_execution_ledger ENABLE ROW LEVEL SECURITY"
        in source
    )
    assert (
        "ALTER TABLE public.alpha_memory_consolidation_execution_ledger FORCE ROW LEVEL SECURITY"
        in source
    )
    assert "review_for_working_decay maps to archive_working" in source
    assert "merge_duplicate_semantic" in source
    assert "review_for_procedural_memory" in source


def test_memory_consolidation_schema_rollback_fails_safely_with_rows() -> None:
    source = ROLLBACK.read_text(encoding="utf-8")

    assert (
        "Refusing rollback: alpha_memory_consolidation_execution_ledger contains rows"
        in source
    )
    assert (
        "Refusing rollback: alpha_memory_consolidation_proposals contains rows"
        in source
    )
    assert (
        "DROP TABLE IF EXISTS public.alpha_memory_consolidation_execution_ledger"
        in source
    )
    assert "DROP TABLE IF EXISTS public.alpha_memory_consolidation_proposals" in source
