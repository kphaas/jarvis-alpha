from __future__ import annotations

from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "migrations"
    / "20260606_094500_beacon_internet_evidence.sql"
)
MIGRATION_SQL = MIGRATION_PATH.read_text(encoding="utf-8")
MEMORY_PROMOTION_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "migrations"
    / "20260606_120000_beacon_memory_promotion.sql"
)
MEMORY_PROMOTION_SQL = MEMORY_PROMOTION_MIGRATION_PATH.read_text(encoding="utf-8")


def test_beacon_migration_creates_expected_tables():
    for table in (
        "alpha_internet_requests",
        "alpha_internet_sources",
        "alpha_internet_evidence",
        "alpha_internet_tool_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in MIGRATION_SQL
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in MIGRATION_SQL
        assert f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY" in MIGRATION_SQL


def test_beacon_migration_has_rls_with_check_and_no_raw_query_column():
    assert MIGRATION_SQL.count("WITH CHECK") >= 4
    assert "query TEXT" not in MIGRATION_SQL
    assert "raw_query" not in MIGRATION_SQL
    assert "request_payload_hash TEXT NOT NULL" in MIGRATION_SQL
    assert "request_shape       JSONB NOT NULL" in MIGRATION_SQL


def test_beacon_tool_events_are_append_only():
    assert "alpha_internet_tool_events_append_only" in MIGRATION_SQL
    assert "trg_alpha_internet_tool_events_no_update" in MIGRATION_SQL
    assert "trg_alpha_internet_tool_events_no_delete" in MIGRATION_SQL
    assert (
        "RAISE EXCEPTION 'alpha_internet_tool_events is append-only'" in MIGRATION_SQL
    )


def test_beacon_migration_grants_runtime_least_privilege():
    assert "GRANT SELECT, INSERT, UPDATE" in MIGRATION_SQL
    assert "ON public.alpha_internet_requests" in MIGRATION_SQL
    assert "public.alpha_internet_sources" in MIGRATION_SQL
    assert "public.alpha_internet_evidence" in MIGRATION_SQL
    assert "public.alpha_internet_tool_events" in MIGRATION_SQL


def test_beacon_memory_promotion_migration_forces_rls():
    assert (
        "CREATE TABLE IF NOT EXISTS public.alpha_internet_memory_promotions"
        in MEMORY_PROMOTION_SQL
    )
    assert (
        "ALTER TABLE public.alpha_internet_memory_promotions ENABLE ROW LEVEL SECURITY"
        in MEMORY_PROMOTION_SQL
    )
    assert (
        "ALTER TABLE public.alpha_internet_memory_promotions FORCE ROW LEVEL SECURITY"
        in MEMORY_PROMOTION_SQL
    )
    assert "WITH CHECK" in MEMORY_PROMOTION_SQL
    assert "alpha_internet_memory_promotions_hash_check" in MEMORY_PROMOTION_SQL


def test_beacon_memory_promotion_function_is_secdef_and_bounded():
    assert "CREATE OR REPLACE FUNCTION public.save_beacon_semantic_memory" in (
        MEMORY_PROMOTION_SQL
    )
    assert "SECURITY DEFINER" in MEMORY_PROMOTION_SQL
    assert "REVOKE ALL ON FUNCTION public.save_beacon_semantic_memory" in (
        MEMORY_PROMOTION_SQL
    )
    assert "OWNER TO jarvisbrain" in MEMORY_PROMOTION_SQL
    assert "source)" in MEMORY_PROMOTION_SQL
    assert "VALUES (p_user_id, btrim(p_fact), p_category, 'promoted')" in (
        MEMORY_PROMOTION_SQL
    )
    assert "char_length(p_fact) > 500" in MEMORY_PROMOTION_SQL
    assert "source_content_hash" in MEMORY_PROMOTION_SQL
