from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260613_195500_spark_personality_memory.sql"
)
REVIEW_ACTIONS_MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260615_090000_spark_personality_memory_review_actions.sql"
)


def test_spark_personality_memory_schema_is_dedicated_and_rls_forced() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS public.alpha_personality_memory" in source
    assert "CREATE OR REPLACE FUNCTION public.list_spark_personality_memory" in source
    assert (
        "ALTER TABLE public.alpha_personality_memory ENABLE ROW LEVEL SECURITY"
        in source
    )
    assert (
        "ALTER TABLE public.alpha_personality_memory FORCE ROW LEVEL SECURITY" in source
    )
    assert "'personality'," not in source
    assert "approved_by" in source
    assert "UNIQUE (principal_id, kind, content)" in source


def test_spark_personality_memory_writer_is_secdef_and_reviewed() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE OR REPLACE FUNCTION public.save_spark_personality_memory" in source
    assert "SECURITY DEFINER" in source
    assert "PERFORM set_config('rls.role', 'platform_admin', true)" in source
    assert "GRANT EXECUTE ON FUNCTION public.list_spark_personality_memory" in source
    assert "GRANT EXECUTE ON FUNCTION public.save_spark_personality_memory" in source
    assert "invalid_approved_by" in source
    assert "invalid_evidence_hash" in source


def test_spark_personality_memory_archive_is_secdef_and_reviewed() -> None:
    source = REVIEW_ACTIONS_MIGRATION.read_text(encoding="utf-8")

    assert (
        "CREATE OR REPLACE FUNCTION public.archive_spark_personality_memory" in source
    )
    assert "SECURITY DEFINER" in source
    assert "PERFORM set_config('rls.role', 'platform_admin', true)" in source
    assert "status = 'archived'" in source
    assert "GRANT EXECUTE ON FUNCTION public.archive_spark_personality_memory" in source
    assert "DROP FUNCTION IF EXISTS public.archive_spark_personality_memory" in source
