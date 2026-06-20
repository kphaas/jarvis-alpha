from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260620_081000_buddy_event_retention_archive.sql"
)
ROLLBACK = (
    REPO_ROOT
    / "brain"
    / "db"
    / "rollbacks"
    / "20260620_081000_buddy_event_retention_archive_rollback.sql"
)
OWNER_GRANTS_MIGRATION = (
    REPO_ROOT
    / "brain"
    / "db"
    / "migrations"
    / "20260620_180000_buddy_maintenance_owner_grants.sql"
)
OWNER_GRANTS_ROLLBACK = (
    REPO_ROOT
    / "brain"
    / "db"
    / "rollbacks"
    / "20260620_180000_buddy_maintenance_owner_grants_rollback.sql"
)
BUDDY_AGENT = REPO_ROOT / "brain" / "agents" / "buddy_agent.py"
SECDEF_CANARY = REPO_ROOT / "scripts" / "postgres_secdef_canary.py"


def test_buddy_event_archive_table_is_force_rls_admin_only() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS public.alpha_buddy_events_archive" in source
    assert (
        "ALTER TABLE public.alpha_buddy_events_archive ENABLE ROW LEVEL SECURITY"
        in source
    )
    assert (
        "ALTER TABLE public.alpha_buddy_events_archive FORCE ROW LEVEL SECURITY"
        in source
    )
    assert "buddy_events_archive_isolation" in source
    assert "current_setting('jarvis.role', true) = 'platform_admin'" in source
    assert "current_setting('rls.role', true) = 'platform_admin'" in source
    assert "GRANT SELECT, INSERT, DELETE ON public.alpha_buddy_events_archive" in source


def test_buddy_event_retention_function_is_bounded_and_safe() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert (
        "CREATE OR REPLACE FUNCTION public.archive_old_low_priority_buddy_events"
        in source
    )
    assert "SECURITY DEFINER" in source
    assert "PERFORM set_config('rls.role', 'platform_admin', true)" in source
    assert "PERFORM set_config('jarvis.role', 'platform_admin', true)" in source
    assert "priority <= 1" in source
    assert "p_batch_limit" in source
    assert "FOR UPDATE SKIP LOCKED" in source
    assert "COALESCE(source, '') <> 'restore_drill_alpha'" in source
    assert "title NOT ILIKE 'Restore drill%'" in source
    assert "pruned_archive_count" in source
    assert (
        "GRANT EXECUTE ON FUNCTION public.archive_old_low_priority_buddy_events"
        in source
    )


def test_buddy_maintenance_reports_retention_counts_without_raw_payload_expansion() -> (
    None
):
    source = MIGRATION.read_text(encoding="utf-8")
    agent = BUDDY_AGENT.read_text(encoding="utf-8")

    assert "public.archive_old_low_priority_buddy_events(14, 180, 5000)" in source
    assert "'archived_buddy_events', v_archived_buddy_events" in source
    assert "'pruned_buddy_event_archive', v_pruned_buddy_event_archive" in source
    assert "archived_buddy_events" in agent
    assert "pruned_buddy_event_archive" in agent


def test_buddy_retention_rollback_fails_safely_when_archive_has_rows() -> None:
    source = ROLLBACK.read_text(encoding="utf-8")

    assert "Refusing rollback: alpha_buddy_events_archive contains rows" in source
    assert (
        "DROP FUNCTION IF EXISTS public.archive_old_low_priority_buddy_events" in source
    )
    assert "DROP TABLE IF EXISTS public.alpha_buddy_events_archive" in source
    assert "CREATE OR REPLACE FUNCTION public.run_buddy_memory_maintenance" in source


def test_buddy_retention_is_in_secdef_canary() -> None:
    source = SECDEF_CANARY.read_text(encoding="utf-8")

    assert "public.archive_old_low_priority_buddy_events(" in source
    assert "SELECT public.archive_old_low_priority_buddy_events(14, 180, 1);" in source


def test_buddy_maintenance_owner_can_execute_all_delegates() -> None:
    source = OWNER_GRANTS_MIGRATION.read_text(encoding="utf-8")

    assert "TO jarvis_alpha_owner" in source
    assert "public.evict_expired_working_memory()" in source
    assert "public.archive_old_low_priority_buddy_events(" in source
    assert "public.evict_episodic_memory_older_than(" in source
    assert "public.cap_episodic_memory(TEXT, INTEGER)" in source
    assert "public.cap_semantic_memory(TEXT, INTEGER)" in source
    assert "has_function_privilege('jarvis_alpha_owner'" in source
    assert "Buddy maintenance owner grant postcheck failed" in source
    assert "Buddy maintenance owner grant restored PUBLIC execute" in source


def test_buddy_maintenance_owner_grants_are_reversible() -> None:
    source = OWNER_GRANTS_ROLLBACK.read_text(encoding="utf-8")

    assert "REVOKE EXECUTE ON FUNCTION public.evict_expired_working_memory()" in source
    assert "REVOKE EXECUTE ON FUNCTION public.archive_old_low_priority_buddy_events(" in source
    assert "REVOKE EXECUTE ON FUNCTION public.evict_episodic_memory_older_than(" in source
    assert "REVOKE EXECUTE ON FUNCTION public.cap_episodic_memory(TEXT, INTEGER)" in source
    assert "REVOKE EXECUTE ON FUNCTION public.cap_semantic_memory(TEXT, INTEGER)" in source
    assert "ARRAY[]::aclitem[]" in source
    assert "Buddy maintenance owner grant rollback left explicit EXECUTE grants" in source
