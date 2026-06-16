from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260616_073500_spark_target_memory.sql"
)


def test_spark_target_memory_schema_is_dedicated_and_rls_forced() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS public.alpha_spark_target_memory" in source
    assert "CREATE OR REPLACE FUNCTION public.list_spark_target_memory" in source
    assert (
        "ALTER TABLE public.alpha_spark_target_memory ENABLE ROW LEVEL SECURITY"
        in source
    )
    assert (
        "ALTER TABLE public.alpha_spark_target_memory FORCE ROW LEVEL SECURITY"
        in source
    )
    assert "target_ref_hash" in source
    assert "target_label" in source
    assert "UNIQUE (principal_id, target_ref_hash, kind, content)" in source


def test_spark_target_memory_writer_and_archive_are_secdef() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE OR REPLACE FUNCTION public.save_spark_target_memory" in source
    assert "CREATE OR REPLACE FUNCTION public.archive_spark_target_memory" in source
    assert "SECURITY DEFINER" in source
    assert "PERFORM set_config('rls.role', 'platform_admin', true)" in source
    assert "invalid_target_ref_hash" in source
    assert "invalid_target_label" in source
    assert "GRANT EXECUTE ON FUNCTION public.list_spark_target_memory" in source
    assert "GRANT EXECUTE ON FUNCTION public.save_spark_target_memory" in source
    assert "GRANT EXECUTE ON FUNCTION public.archive_spark_target_memory" in source
