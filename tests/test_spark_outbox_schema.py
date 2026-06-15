from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT / "brain" / "db" / "migrations" / "20260615_190000_spark_outbox_audit.sql"
)


def test_spark_outbox_schema_is_encrypted_and_rls_forced() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS public.alpha_spark_outbox" in source
    assert "CREATE TABLE IF NOT EXISTS public.alpha_spark_outbox_events" in source
    assert "draft_text_ciphertext    BYTEA NOT NULL" in source
    assert "draft_text_hash          TEXT NOT NULL" in source
    assert "REFERENCES public.alpha_approval_queue(id)" in source
    assert "ALTER TABLE public.alpha_spark_outbox FORCE ROW LEVEL SECURITY" in source
    assert (
        "ALTER TABLE public.alpha_spark_outbox_events FORCE ROW LEVEL SECURITY"
        in source
    )
    assert "alpha_spark_outbox_events is append-only" in source


def test_spark_outbox_writes_are_secdef_and_metadata_only() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE OR REPLACE FUNCTION public.create_spark_outbox_item" in source
    assert "CREATE OR REPLACE FUNCTION public.list_spark_outbox_items" in source
    assert "SECURITY DEFINER" in source
    assert "PERFORM set_config('rls.role', 'platform_admin', true)" in source
    assert "GRANT EXECUTE ON FUNCTION public.create_spark_outbox_item" in source
    assert "GRANT EXECUTE ON FUNCTION public.list_spark_outbox_items" in source
    assert "draft_text_ciphertext" not in _list_function_body(source)
    assert "draft_text text" not in _list_function_body(source)
    assert "draft_text," not in _list_function_body(source)
    assert "CREATE OR REPLACE FUNCTION public.decrypt" not in source
    assert "CREATE OR REPLACE FUNCTION public.spark_outbox_decrypt" not in source
    assert "p.proname ILIKE '%spark%outbox%decrypt%'" in source


def test_spark_outbox_has_explicit_downgrade() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "-- Downgrade:" in source
    assert "DROP TABLE IF EXISTS public.alpha_spark_outbox_events" in source
    assert "DROP TABLE IF EXISTS public.alpha_spark_outbox" in source


def _list_function_body(source: str) -> str:
    start = source.index("CREATE OR REPLACE FUNCTION public.list_spark_outbox_items")
    end = source.index(
        "REVOKE ALL ON FUNCTION public.create_spark_outbox_item",
        start,
    )
    return source[start:end]
