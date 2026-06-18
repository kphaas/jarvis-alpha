from __future__ import annotations

import os
from pathlib import Path

import asyncpg
import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "migrations"
    / "20260605_010000_privacy_scrub_foundations.sql"
)
TARGET_CACHE_RLS_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "migrations"
    / "20260605_073000_privacy_targets_cache_rls.sql"
)
CASE_DRAFTS_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "migrations"
    / "20260605_120000_privacy_case_drafts.sql"
)
MANUAL_WORKFLOW_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "migrations"
    / "20260606_090000_privacy_manual_workflow.sql"
)
CASE_COMPLETED_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "migrations"
    / "20260606_111500_privacy_case_draft_completed_status.sql"
)
CASE_COMPLETED_ROLLBACK_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "rollbacks"
    / "20260606_111500_privacy_case_draft_completed_status_rollback.sql"
)
REMOVAL_CONTROL_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "migrations"
    / "20260606_173000_privacy_removal_control_plane.sql"
)
REMOVAL_CONTROL_ROLLBACK_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "rollbacks"
    / "20260606_173000_privacy_removal_control_plane_rollback.sql"
)
LIFECYCLE_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "migrations"
    / "20260618_090000_privacy_authorization_lifecycle.sql"
)
LIFECYCLE_ROLLBACK_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "rollbacks"
    / "20260618_090000_privacy_authorization_lifecycle_rollback.sql"
)
DRY_RUN_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "migrations"
    / "20260618_100000_privacy_gateway_dry_run.sql"
)
DRY_RUN_ROLLBACK_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "rollbacks"
    / "20260618_100000_privacy_gateway_dry_run_rollback.sql"
)
LIVE_PREFLIGHT_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "migrations"
    / "20260618_110000_privacy_gateway_live_preflight.sql"
)
LIVE_PREFLIGHT_ROLLBACK_PATH = (
    Path(__file__).resolve().parents[1]
    / "brain"
    / "db"
    / "rollbacks"
    / "20260618_110000_privacy_gateway_live_preflight_rollback.sql"
)

MIGRATION_SQL = MIGRATION_PATH.read_text(encoding="utf-8")
TARGET_CACHE_RLS_SQL = TARGET_CACHE_RLS_MIGRATION_PATH.read_text(encoding="utf-8")
CASE_DRAFTS_SQL = CASE_DRAFTS_MIGRATION_PATH.read_text(encoding="utf-8")
MANUAL_WORKFLOW_SQL = MANUAL_WORKFLOW_MIGRATION_PATH.read_text(encoding="utf-8")
CASE_COMPLETED_SQL = CASE_COMPLETED_MIGRATION_PATH.read_text(encoding="utf-8")
CASE_COMPLETED_ROLLBACK_SQL = CASE_COMPLETED_ROLLBACK_PATH.read_text(encoding="utf-8")
REMOVAL_CONTROL_SQL = REMOVAL_CONTROL_MIGRATION_PATH.read_text(encoding="utf-8")
REMOVAL_CONTROL_ROLLBACK_SQL = REMOVAL_CONTROL_ROLLBACK_PATH.read_text(
    encoding="utf-8",
)
LIFECYCLE_SQL = LIFECYCLE_MIGRATION_PATH.read_text(encoding="utf-8")
LIFECYCLE_ROLLBACK_SQL = LIFECYCLE_ROLLBACK_PATH.read_text(encoding="utf-8")
DRY_RUN_SQL = DRY_RUN_MIGRATION_PATH.read_text(encoding="utf-8")
DRY_RUN_ROLLBACK_SQL = DRY_RUN_ROLLBACK_PATH.read_text(encoding="utf-8")
LIVE_PREFLIGHT_SQL = LIVE_PREFLIGHT_MIGRATION_PATH.read_text(encoding="utf-8")
LIVE_PREFLIGHT_ROLLBACK_SQL = LIVE_PREFLIGHT_ROLLBACK_PATH.read_text(
    encoding="utf-8",
)


def test_migration_uses_force_rls_on_sensitive_tables():
    for table in (
        "alpha_privacy_subjects",
        "alpha_privacy_identity_tuples",
        "alpha_privacy_scans",
        "alpha_privacy_discoveries",
        "alpha_privacy_actions",
        "alpha_privacy_action_events",
    ):
        assert f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY" in MIGRATION_SQL


def test_targets_cache_followup_enables_force_rls():
    assert (
        "ALTER TABLE public.alpha_privacy_targets_cache ENABLE ROW LEVEL SECURITY"
        in TARGET_CACHE_RLS_SQL
    )
    assert (
        "ALTER TABLE public.alpha_privacy_targets_cache FORCE ROW LEVEL SECURITY"
        in TARGET_CACHE_RLS_SQL
    )
    assert "alpha_privacy_targets_cache_platform_admin" in TARGET_CACHE_RLS_SQL
    assert (
        "current_setting('rls.role', true) = 'platform_admin'" in TARGET_CACHE_RLS_SQL
    )


def test_case_drafts_migration_enables_force_rls_and_action_linkage():
    assert "CREATE TABLE IF NOT EXISTS public.alpha_privacy_case_drafts" in (
        CASE_DRAFTS_SQL
    )
    assert (
        "ALTER TABLE public.alpha_privacy_case_drafts ENABLE ROW LEVEL SECURITY"
        in CASE_DRAFTS_SQL
    )
    assert (
        "ALTER TABLE public.alpha_privacy_case_drafts FORCE ROW LEVEL SECURITY"
        in CASE_DRAFTS_SQL
    )
    assert "privacy_case_drafts_isolation" in CASE_DRAFTS_SQL
    assert "ADD COLUMN IF NOT EXISTS case_draft_id UUID" in CASE_DRAFTS_SQL
    assert "ON DELETE RESTRICT" in CASE_DRAFTS_SQL
    assert "packet_payload_ciphertext    BYTEA NOT NULL" in CASE_DRAFTS_SQL
    assert "GRANT SELECT, INSERT, UPDATE" in CASE_DRAFTS_SQL


def test_manual_workflow_migration_stores_only_encrypted_notes_and_hashes():
    assert "manual_note_ciphertext BYTEA" in MANUAL_WORKFLOW_SQL
    assert "evidence_payload_ciphertext BYTEA" in MANUAL_WORKFLOW_SQL
    assert "manual_note_hash TEXT" in MANUAL_WORKFLOW_SQL
    assert "evidence_payload_hash TEXT" in MANUAL_WORKFLOW_SQL
    assert "privacy_action_manual_disposition_check" in MANUAL_WORKFLOW_SQL
    assert "'handled', 'deferred', 'blocked'" in MANUAL_WORKFLOW_SQL
    assert "privacy_decrypt_payload" in MANUAL_WORKFLOW_SQL
    assert "CREATE OR REPLACE FUNCTION public.privacy_decrypt_payload" not in (
        MANUAL_WORKFLOW_SQL
    )
    assert "operator_note TEXT" not in MANUAL_WORKFLOW_SQL
    assert "evidence_reference TEXT" not in MANUAL_WORKFLOW_SQL


def test_case_completed_status_migration_has_reversible_constraint_change():
    assert "alpha_privacy_case_drafts_status_check" in CASE_COMPLETED_SQL
    assert "'completed'" in CASE_COMPLETED_SQL
    assert "DROP CONSTRAINT IF EXISTS alpha_privacy_case_drafts_status_check" in (
        CASE_COMPLETED_SQL
    )
    assert "UPDATE public.alpha_privacy_case_drafts" in CASE_COMPLETED_ROLLBACK_SQL
    assert "SET status = 'submitted_for_approval'" in CASE_COMPLETED_ROLLBACK_SQL
    assert (
        "'completed'"
        not in CASE_COMPLETED_ROLLBACK_SQL.split(
            "ADD CONSTRAINT alpha_privacy_case_drafts_status_check",
            1,
        )[1]
    )


def test_removal_control_migration_covers_p4_lanes_with_force_rls():
    for table in (
        "alpha_privacy_authorizations",
        "alpha_privacy_adapter_profiles",
        "alpha_privacy_evidence_items",
        "alpha_privacy_monitor_runs",
        "alpha_privacy_search_deindex_items",
        "alpha_privacy_public_record_triage",
    ):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in REMOVAL_CONTROL_SQL
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in (
            REMOVAL_CONTROL_SQL
        )
        assert f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY" in (
            REMOVAL_CONTROL_SQL
        )

    assert "privacy_authorizations_isolation" in REMOVAL_CONTROL_SQL
    assert "privacy_evidence_items_isolation" in REMOVAL_CONTROL_SQL
    assert "privacy_monitor_runs_isolation" in REMOVAL_CONTROL_SQL
    assert "privacy_search_deindex_items_isolation" in REMOVAL_CONTROL_SQL
    assert "privacy_public_record_triage_isolation" in REMOVAL_CONTROL_SQL
    assert "privacy_adapter_profiles_read" in REMOVAL_CONTROL_SQL


def test_removal_control_migration_keeps_sensitive_values_encrypted():
    assert "authorization_payload_ciphertext" in REMOVAL_CONTROL_SQL
    assert "evidence_payload_ciphertext" in REMOVAL_CONTROL_SQL
    assert "report_payload_ciphertext" in REMOVAL_CONTROL_SQL
    assert "item_payload_ciphertext" in REMOVAL_CONTROL_SQL
    assert "triage_payload_ciphertext" in REMOVAL_CONTROL_SQL
    assert "result_url_digest" in REMOVAL_CONTROL_SQL
    assert "privacy_decrypt_payload" in REMOVAL_CONTROL_SQL
    assert "CREATE OR REPLACE FUNCTION public.privacy_decrypt_payload" not in (
        REMOVAL_CONTROL_SQL
    )
    forbidden = (
        "display_name",
        " dob ",
        "match_url           TEXT",
        "metadata JSONB",
        "error_message",
        "result_url TEXT",
        "authorization_text",
    )
    for token in forbidden:
        assert token not in REMOVAL_CONTROL_SQL


def test_removal_control_migration_has_rollback_for_every_new_table():
    for table in (
        "alpha_privacy_public_record_triage",
        "alpha_privacy_search_deindex_items",
        "alpha_privacy_monitor_runs",
        "alpha_privacy_evidence_items",
        "alpha_privacy_adapter_profiles",
        "alpha_privacy_authorizations",
    ):
        assert f"DROP TABLE IF EXISTS public.{table}" in REMOVAL_CONTROL_ROLLBACK_SQL


def test_authorization_lifecycle_migration_adds_force_rls_request_ledger():
    for table in (
        "alpha_privacy_removal_requests",
        "alpha_privacy_removal_request_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in LIFECYCLE_SQL
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in (
            LIFECYCLE_SQL
        )
        assert f"ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY" in (LIFECYCLE_SQL)

    assert "privacy_removal_requests_isolation" in LIFECYCLE_SQL
    assert "privacy_removal_request_events_isolation" in LIFECYCLE_SQL
    assert "lifecycle_status" in LIFECYCLE_SQL
    assert "'completed'" in LIFECYCLE_SQL
    assert "removal_request_id UUID" in LIFECYCLE_SQL
    assert "REFERENCES public.alpha_privacy_removal_requests" in LIFECYCLE_SQL


def test_authorization_lifecycle_migration_keeps_payloads_encrypted():
    assert "request_payload_ciphertext" in LIFECYCLE_SQL
    assert "request_payload_hash" in LIFECYCLE_SQL
    assert "event_payload_ciphertext" in LIFECYCLE_SQL
    assert "event_payload_hash" in LIFECYCLE_SQL
    assert "CREATE OR REPLACE FUNCTION public.privacy_decrypt_payload" not in (
        LIFECYCLE_SQL
    )
    forbidden = (
        "authorization_text",
        "request_body TEXT",
        "proof_url TEXT",
        "response_body TEXT",
        "metadata JSONB",
    )
    for token in forbidden:
        assert token not in LIFECYCLE_SQL


def test_authorization_lifecycle_migration_has_rollback():
    assert "DROP COLUMN IF EXISTS removal_request_id" in LIFECYCLE_ROLLBACK_SQL
    assert (
        "DROP TABLE IF EXISTS public.alpha_privacy_removal_request_events"
        in LIFECYCLE_ROLLBACK_SQL
    )
    assert (
        "DROP TABLE IF EXISTS public.alpha_privacy_removal_requests"
        in LIFECYCLE_ROLLBACK_SQL
    )


def test_gateway_dry_run_migration_adds_encrypted_gateway_proof_columns():
    assert "dry_run_payload_ciphertext BYTEA" in DRY_RUN_SQL
    assert "dry_run_payload_hash TEXT" in DRY_RUN_SQL
    assert "dry_run_payload_key_version TEXT" in DRY_RUN_SQL
    assert "gateway_idempotency_key_digest TEXT" in DRY_RUN_SQL
    assert "'dry_run_prepared'" in DRY_RUN_SQL
    assert "privacy_gateway_dry-run must not expose decrypt helpers" not in (
        DRY_RUN_SQL
    )
    assert "CREATE OR REPLACE FUNCTION public.privacy_decrypt_payload" not in (
        DRY_RUN_SQL
    )
    assert "relrowsecurity AND relforcerowsecurity" in DRY_RUN_SQL


def test_gateway_dry_run_migration_avoids_plaintext_executor_payloads():
    forbidden = (
        "request_body TEXT",
        "response_body TEXT",
        "broker_response TEXT",
        "metadata JSONB",
        "idempotency_key TEXT",
        "target_url TEXT",
    )
    for token in forbidden:
        assert token not in DRY_RUN_SQL


def test_gateway_dry_run_migration_has_rollback():
    assert "SET event_type = 'note'" in DRY_RUN_ROLLBACK_SQL
    assert "DROP COLUMN IF EXISTS dry_run_payload_ciphertext" in DRY_RUN_ROLLBACK_SQL
    assert "DROP COLUMN IF EXISTS dry_run_payload_hash" in DRY_RUN_ROLLBACK_SQL
    assert "DROP COLUMN IF EXISTS gateway_idempotency_key_digest" in (
        DRY_RUN_ROLLBACK_SQL
    )
    assert (
        "'dry_run_prepared'"
        not in DRY_RUN_ROLLBACK_SQL.split(
            "ADD CONSTRAINT privacy_removal_request_events_event_type_check",
            1,
        )[1]
    )


def test_gateway_live_preflight_migration_adds_encrypted_proof_columns():
    assert "live_preflight_payload_ciphertext BYTEA" in LIVE_PREFLIGHT_SQL
    assert "live_preflight_payload_hash TEXT" in LIVE_PREFLIGHT_SQL
    assert "live_preflight_payload_key_version TEXT" in LIVE_PREFLIGHT_SQL
    assert "live_preflight_approval_queue_id UUID" in LIVE_PREFLIGHT_SQL
    assert "REFERENCES public.alpha_approval_queue(id)" in LIVE_PREFLIGHT_SQL
    assert "'live_disabled'" in LIVE_PREFLIGHT_SQL
    assert "'live_preflight_passed'" in LIVE_PREFLIGHT_SQL
    assert "'live_preflight_failed'" in LIVE_PREFLIGHT_SQL
    assert "CREATE OR REPLACE FUNCTION public.privacy_decrypt_payload" not in (
        LIVE_PREFLIGHT_SQL
    )
    assert "relrowsecurity AND relforcerowsecurity" in LIVE_PREFLIGHT_SQL


def test_gateway_live_preflight_migration_avoids_plaintext_executor_payloads():
    forbidden = (
        "request_body TEXT",
        "response_body TEXT",
        "broker_response TEXT",
        "metadata JSONB",
        "idempotency_key TEXT",
        "target_url TEXT",
        "approval_token TEXT",
    )
    for token in forbidden:
        assert token not in LIVE_PREFLIGHT_SQL


def test_gateway_live_preflight_migration_has_rollback():
    assert "SET event_type = 'note'" in LIVE_PREFLIGHT_ROLLBACK_SQL
    assert "DROP COLUMN IF EXISTS live_preflight_payload_ciphertext" in (
        LIVE_PREFLIGHT_ROLLBACK_SQL
    )
    assert "DROP COLUMN IF EXISTS live_preflight_payload_hash" in (
        LIVE_PREFLIGHT_ROLLBACK_SQL
    )
    assert "DROP COLUMN IF EXISTS live_preflight_approval_queue_id" in (
        LIVE_PREFLIGHT_ROLLBACK_SQL
    )
    assert (
        "'live_preflight_passed'"
        not in LIVE_PREFLIGHT_ROLLBACK_SQL.split(
            "ADD CONSTRAINT privacy_removal_request_events_event_type_check",
            1,
        )[1]
    )


def test_migration_policies_have_with_check():
    assert MIGRATION_SQL.count("WITH CHECK") >= 6
    assert CASE_DRAFTS_SQL.count("WITH CHECK") >= 1
    assert REMOVAL_CONTROL_SQL.count("WITH CHECK") >= 6
    assert LIFECYCLE_SQL.count("WITH CHECK") >= 2


def test_migration_has_no_public_decrypt_helper():
    assert (
        "CREATE OR REPLACE FUNCTION public.privacy_decrypt_payload" not in MIGRATION_SQL
    )
    assert "get_privacy_payload" not in MIGRATION_SQL.split("DO $$", 1)[0]
    assert (
        "CREATE OR REPLACE FUNCTION public.privacy_decrypt_payload"
        not in REMOVAL_CONTROL_SQL
    )
    assert (
        "CREATE OR REPLACE FUNCTION public.privacy_decrypt_payload" not in LIFECYCLE_SQL
    )
    assert (
        "CREATE OR REPLACE FUNCTION public.privacy_decrypt_payload" not in DRY_RUN_SQL
    )
    assert (
        "CREATE OR REPLACE FUNCTION public.privacy_decrypt_payload"
        not in LIVE_PREFLIGHT_SQL
    )


def test_migration_avoids_plaintext_sensitive_columns():
    forbidden = (
        "display_name",
        " dob ",
        "match_url           TEXT",
        "metadata JSONB",
        "error_message",
    )
    for token in forbidden:
        assert token not in MIGRATION_SQL
        assert token not in CASE_DRAFTS_SQL
        assert token not in MANUAL_WORKFLOW_SQL
        assert token not in REMOVAL_CONTROL_SQL
        assert token not in DRY_RUN_SQL
        assert token not in LIVE_PREFLIGHT_SQL


def test_migration_adds_approval_and_append_only_controls():
    assert "REFERENCES public.alpha_approval_queue(id)" in MIGRATION_SQL
    assert "alpha_privacy_action_events" in MIGRATION_SQL
    assert "privacy_action_events_append_only" in MIGRATION_SQL
    assert "privacy_enforce_action_tier" in MIGRATION_SQL
    assert "'send_opt_out', 'scan_external', 'verify'" in MIGRATION_SQL


def test_migration_does_not_cascade_delete_privacy_records():
    assert "ON DELETE CASCADE" not in MIGRATION_SQL
    assert "ON DELETE CASCADE" not in REMOVAL_CONTROL_SQL
    assert "ON DELETE CASCADE" not in DRY_RUN_SQL
    assert "ON DELETE CASCADE" not in LIVE_PREFLIGHT_SQL


@pytest.fixture
async def db():
    dsn = os.environ.get("TEST_PG_DSN")
    if not dsn:
        pytest.skip("TEST_PG_DSN not set; skipping DB integration test")
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            """
            DROP TABLE IF EXISTS
                alpha_privacy_public_record_triage,
                alpha_privacy_search_deindex_items,
                alpha_privacy_monitor_runs,
                alpha_privacy_evidence_items,
                alpha_privacy_adapter_profiles,
                alpha_privacy_authorizations,
                alpha_privacy_action_events,
                alpha_privacy_actions,
                alpha_privacy_discoveries,
                alpha_privacy_scans,
                alpha_privacy_identity_tuples,
                alpha_privacy_subjects,
                alpha_privacy_targets_cache CASCADE
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS public.alpha_approval_queue (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid()
            )
            """
        )
        yield conn
    finally:
        await conn.close()


async def _apply_migration(conn: asyncpg.Connection) -> None:
    await conn.execute(MIGRATION_SQL)


async def _apply_removal_control_migration(conn: asyncpg.Connection) -> None:
    await _apply_migration(conn)
    await conn.execute(REMOVAL_CONTROL_SQL)


@pytest.mark.asyncio
async def test_migration_creates_all_tables(db):
    await _apply_migration(db)
    rows = await db.fetch(
        """
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename LIKE 'alpha_privacy_%'
        ORDER BY tablename
        """
    )
    names = {row["tablename"] for row in rows}

    assert {
        "alpha_privacy_action_events",
        "alpha_privacy_actions",
        "alpha_privacy_discoveries",
        "alpha_privacy_identity_tuples",
        "alpha_privacy_scans",
        "alpha_privacy_subjects",
        "alpha_privacy_targets_cache",
    }.issubset(names)


@pytest.mark.asyncio
async def test_removal_control_migration_creates_p4_tables(db):
    await _apply_removal_control_migration(db)
    rows = await db.fetch(
        """
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename LIKE 'alpha_privacy_%'
        ORDER BY tablename
        """
    )
    names = {row["tablename"] for row in rows}

    assert {
        "alpha_privacy_authorizations",
        "alpha_privacy_adapter_profiles",
        "alpha_privacy_evidence_items",
        "alpha_privacy_monitor_runs",
        "alpha_privacy_search_deindex_items",
        "alpha_privacy_public_record_triage",
    }.issubset(names)


@pytest.mark.asyncio
async def test_rls_forced_on_pii_tables(db):
    await _apply_migration(db)
    rows = await db.fetch(
        """
        SELECT relname, relrowsecurity, relforcerowsecurity
        FROM pg_class
        WHERE relname IN (
            'alpha_privacy_subjects',
            'alpha_privacy_identity_tuples',
            'alpha_privacy_scans',
            'alpha_privacy_discoveries',
            'alpha_privacy_actions',
            'alpha_privacy_action_events'
        )
        """
    )

    assert rows
    for row in rows:
        assert row["relrowsecurity"] is True
        assert row["relforcerowsecurity"] is True


@pytest.mark.asyncio
async def test_rls_forced_on_removal_control_tables(db):
    await _apply_removal_control_migration(db)
    rows = await db.fetch(
        """
        SELECT relname, relrowsecurity, relforcerowsecurity
        FROM pg_class
        WHERE relname IN (
            'alpha_privacy_authorizations',
            'alpha_privacy_adapter_profiles',
            'alpha_privacy_evidence_items',
            'alpha_privacy_monitor_runs',
            'alpha_privacy_search_deindex_items',
            'alpha_privacy_public_record_triage'
        )
        """
    )

    assert rows
    for row in rows:
        assert row["relrowsecurity"] is True
        assert row["relforcerowsecurity"] is True


@pytest.mark.asyncio
async def test_minor_unsafe_action_rejected_by_db_trigger(db):
    await _apply_migration(db)
    await db.execute("SELECT set_config('rls.role', 'platform_admin', false)")
    await db.execute("SELECT set_config('rls.user_id', 'ken', false)")
    target_id = "test_target"
    await db.execute(
        """
        INSERT INTO public.alpha_privacy_targets_cache (
            id, name, category, jurisdiction, opt_out_method, yaml_source
        )
        VALUES ($1, 'Target', 'data_broker', 'US_FEDERAL', 'web_form', 'test')
        """,
        target_id,
    )
    subject_id = await db.fetchval(
        """
        INSERT INTO public.alpha_privacy_subjects (
            user_id, display_label_digest, role, guardian_user_id,
            subject_payload_ciphertext, subject_payload_hash,
            subject_payload_key_version
        )
        VALUES (
            'ken',
            'hmac-sha256:1111111111111111111111111111111111111111111111111111111111111111',
            'minor',
            'ken',
            public.privacy_encrypt_payload('subject', 'k'),
            'sha256:1111111111111111111111111111111111111111111111111111111111111111',
            'v1'
        )
        RETURNING id
        """
    )

    with pytest.raises(asyncpg.RaiseError, match="minor external privacy"):
        await db.execute(
            """
            INSERT INTO public.alpha_privacy_actions (
                subject_id, target_id, action_type, approval_tier
            )
            VALUES ($1, $2, 'send_opt_out', 'T4')
            """,
            subject_id,
            target_id,
        )


@pytest.mark.asyncio
async def test_action_events_are_append_only(db):
    await _apply_migration(db)
    await db.execute("SELECT set_config('rls.role', 'platform_admin', false)")
    await db.execute("SELECT set_config('rls.user_id', 'ken', false)")
    await db.execute(
        """
        INSERT INTO public.alpha_privacy_targets_cache (
            id, name, category, jurisdiction, opt_out_method, yaml_source
        )
        VALUES ('append_target', 'Target', 'data_broker', 'US_FEDERAL', 'web_form', 'test')
        """
    )
    subject_id = await db.fetchval(
        """
        INSERT INTO public.alpha_privacy_subjects (
            user_id, display_label_digest, role, subject_payload_ciphertext,
            subject_payload_hash, subject_payload_key_version
        )
        VALUES (
            'ken',
            'hmac-sha256:2222222222222222222222222222222222222222222222222222222222222222',
            'adult',
            public.privacy_encrypt_payload('subject', 'k'),
            'sha256:2222222222222222222222222222222222222222222222222222222222222222',
            'v1'
        )
        RETURNING id
        """
    )
    action_id = await db.fetchval(
        """
        INSERT INTO public.alpha_privacy_actions (
            subject_id, target_id, action_type, approval_tier
        )
        VALUES ($1, 'append_target', 'scan_local', 'T1')
        RETURNING id
        """,
        subject_id,
    )
    event_id = await db.fetchval(
        """
        INSERT INTO public.alpha_privacy_action_events (
            action_id, event_type, actor
        )
        VALUES ($1, 'created', 'test')
        RETURNING id
        """,
        action_id,
    )

    with pytest.raises(asyncpg.RaiseError, match="append-only"):
        await db.execute(
            "UPDATE public.alpha_privacy_action_events SET actor = 'other' WHERE id = $1",
            event_id,
        )
