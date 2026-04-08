-- 20260408_011144_create_schema_migrations.sql
-- Tracking table for the canonical migration runner.
-- See brain/db/migrations/README.md for the full migration system spec.
--
-- Columns:
--   filename          — exact filename in brain/db/migrations/ (PRIMARY KEY)
--   checksum          — SHA-256 hex digest of file content at time of apply
--   applied_at        — when the runner applied this file
--   applied_by        — Postgres user that applied it (current_user)
--   execution_time_ms — how long the file took to execute
--   source            — 'runner' (normal apply) or 'pre-tracking' (backfilled
--                        from history before this table existed)

BEGIN;

CREATE TABLE IF NOT EXISTS schema_migrations (
    filename          TEXT PRIMARY KEY,
    checksum          TEXT NOT NULL,
    applied_at        TIMESTAMPTZ DEFAULT NOW(),
    applied_by        TEXT NOT NULL DEFAULT current_user,
    execution_time_ms INTEGER,
    source            TEXT NOT NULL DEFAULT 'runner'
        CHECK (source IN ('runner', 'pre-tracking', 'baseline'))
);

CREATE INDEX IF NOT EXISTS idx_schema_migrations_applied_at
    ON schema_migrations (applied_at DESC);

COMMENT ON TABLE schema_migrations IS
    'Migration tracking table for the canonical bash runner. '
    'Filenames are immutable once applied. Checksum mismatch on re-run = abort.';

COMMIT;
