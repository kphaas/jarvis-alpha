-- 20260408_013542_drop_alembic_version.sql
-- Phase 2: Drop the stale Alembic tracking table.
--
-- Background:
-- The db/alembic/ directory was deprecated on April 7, 2026 in favor of the
-- canonical migration system at brain/db/migrations/. The alembic_version
-- table on Brain held a single row referencing the last Alembic migration
-- applied (003_chat_threads). It is no longer read or written by anything.
--
-- This migration drops the table. The 3 historical Alembic Python files in
-- db/alembic/versions/ remain on disk as frozen historical reference.
--
-- Reversible: To recreate, run `alembic stamp head` from the repo root
-- (would require restoring the historical alembic_version row manually).
--
-- See db/alembic/README.md for the full deprecation rationale.

BEGIN;

DROP TABLE IF EXISTS alembic_version;

COMMIT;
