-- TD-X40 — Cleanup orphan schema_migrations row
-- 004_taskgraph_columns.sql was recorded in schema_migrations but the file
-- no longer exists on disk (superseded by later TaskGraph migrations).
-- Remove the orphan row to bring schema_migrations in sync with disk state.
--
-- Refs: jarvis-standards#49 (TD-X40)
-- Safe to apply on both jarvis_alpha and jarvis_alpha_test.

BEGIN;

DELETE FROM schema_migrations
WHERE filename = '004_taskgraph_columns.sql';

-- Sanity check: must remove exactly 1 row in jarvis_alpha, 0 rows in test
-- (test never had this row). No assertion enforced — runner records its
-- own row on success.

COMMIT;
