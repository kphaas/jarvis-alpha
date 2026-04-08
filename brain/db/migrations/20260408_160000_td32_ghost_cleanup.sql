-- Migration 20260408_160000: TD-32 ghost migration cleanup (Step 6.5 Stage 4)
-- Deletes the ghost row for 008_buddy_events.sql from schema_migrations.
-- Per STAGE4_DISCOVERY.md: 008 was a no-op that rolled back on CREATE POLICY.
-- Live alpha_buddy_events is built by 005_buddy_events.sql + 011_buddy_events_columns.sql
-- + 20260408_140000_record_buddy_event_fix.sql. 008 contributes nothing.
-- The 008 file itself is being deleted from the repo in the same commit.

-- Delete the ghost row. applied_at IS NULL on this row, proving it was fake.
DELETE FROM public.schema_migrations
WHERE filename = '008_buddy_events.sql' AND applied_at IS NULL;

-- Also clean the orphan 004_taskgraph_columns.sql ghost flagged in earlier discovery
-- (file doesn't exist in repo but has a row in schema_migrations)
-- Deferred per handoff #02 — NOT cleaned in this migration. TD-41 will handle it.
