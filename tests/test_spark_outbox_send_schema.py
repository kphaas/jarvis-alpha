from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260615_193000_spark_outbox_send_executor.sql"
)


def test_spark_outbox_send_schema_uses_secdef_helpers() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE OR REPLACE FUNCTION public.get_spark_outbox_item_for_send" in source
    assert "CREATE OR REPLACE FUNCTION public.record_spark_outbox_event" in source
    assert "SECURITY DEFINER" in source
    assert "PERFORM set_config('rls.role', 'platform_admin', true)" in source
    assert "GRANT EXECUTE ON FUNCTION public.get_spark_outbox_item_for_send" in source
    assert "GRANT EXECUTE ON FUNCTION public.record_spark_outbox_event" in source


def test_spark_outbox_send_schema_keeps_decrypt_app_side() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "draft_text_ciphertext bytea" in source
    assert "CREATE OR REPLACE FUNCTION public.decrypt" not in source
    assert "CREATE OR REPLACE FUNCTION public.spark_outbox_decrypt" not in source
    assert "p.proname ILIKE '%spark%outbox%decrypt%'" in source
    assert "consume_approved_queue_item" not in source


def test_spark_outbox_send_schema_has_status_transitions_and_downgrade() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "status = 'sending'" in source
    assert "status = 'sent'" in source
    assert "status = 'send_failed'" in source
    assert "DROP FUNCTION IF EXISTS public.record_spark_outbox_event" in source
    assert "DROP FUNCTION IF EXISTS public.get_spark_outbox_item_for_send" in source
