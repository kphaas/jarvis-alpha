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
