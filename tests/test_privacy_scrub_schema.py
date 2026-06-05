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

MIGRATION_SQL = MIGRATION_PATH.read_text(encoding="utf-8")


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


def test_migration_policies_have_with_check():
    assert MIGRATION_SQL.count("WITH CHECK") >= 6


def test_migration_has_no_public_decrypt_helper():
    assert (
        "CREATE OR REPLACE FUNCTION public.privacy_decrypt_payload" not in MIGRATION_SQL
    )
    assert "get_privacy_payload" not in MIGRATION_SQL.split("DO $$", 1)[0]


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


def test_migration_adds_approval_and_append_only_controls():
    assert "REFERENCES public.alpha_approval_queue(id)" in MIGRATION_SQL
    assert "alpha_privacy_action_events" in MIGRATION_SQL
    assert "privacy_action_events_append_only" in MIGRATION_SQL
    assert "privacy_enforce_action_tier" in MIGRATION_SQL
    assert "'send_opt_out', 'scan_external', 'verify'" in MIGRATION_SQL


def test_migration_does_not_cascade_delete_privacy_records():
    assert "ON DELETE CASCADE" not in MIGRATION_SQL


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
