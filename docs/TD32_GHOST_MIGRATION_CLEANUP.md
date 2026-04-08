# TD-32: 008_buddy_events.sql Ghost Migration — RESOLVED

**Status:** RESOLVED in Step 6.5 Stage 4 (2026-04-08)
**Audit:** docs/STAGE4_DISCOVERY.md
**Closed By:** migration 20260408_160000_td32_ghost_cleanup.sql

## What Happened

Migration 008_buddy_events.sql was written assuming a TaskGraph-centric buddy events model:
- Required columns: graph_id (UUID FK to alpha_task_graphs), step_id, message
- event_type CHECK: graph_complete | graph_halted | step_failed | step_retrying | ci_required | approval_required
- RLS policy buddy_events_isolation referencing alpha_task_graphs.created_by

The real alpha_buddy_events (created by 005_buddy_events.sql) is a user-centric alert/notification model:
- Columns: id, user_id, event_type, title, body, priority, read, created_at, source, payload
- event_type CHECK: alert | reminder | suggestion | system
- priority INTEGER 1-3

When 008 ran:
1. CREATE TABLE IF NOT EXISTS fired the guard (table already existed from 005) — no-op
2. ENABLE ROW LEVEL SECURITY ran
3. CREATE POLICY buddy_events_isolation FAILED — graph_id column doesn't exist
4. Transaction rolled back entirely (including the ENABLE RLS)
5. The migration runner marked it failed

Later, the backfill_schema_migrations.sql bootstrap inserted a row for 008 into schema_migrations with applied_at=NULL. This "ghost row" caused the migration runner to skip 008 forever, hiding the problem.

## Investigation

STAGE4_DISCOVERY.md audited:
- Task 1: 005_buddy_events.sql creates the real table (8 of 10 columns)
- Task 2: 011_buddy_events_columns.sql adds source + payload
- Task 3: 20260408_140000_record_buddy_event_fix.sql set priority to INTEGER
- Task 4: Zero migrations reference 008's dead columns (graph_id, step_id, message) on alpha_buddy_events
- Task 5: Zero Python code references 008's dead columns on alpha_buddy_events
- Task 6: Zero external references to 008_buddy_events except docs (historical) and the backfill (ghost row source)
- Task 7: No migration depends on 008

Verdict: SAFE TO DELETE.

## Resolution

Stage 4 cleanup migration (20260408_160000_td32_ghost_cleanup.sql):
1. DELETE the ghost row from schema_migrations WHERE filename = '008_buddy_events.sql' AND applied_at IS NULL
2. Delete 008_buddy_events.sql from the repo (git rm)

Result:
- schema_migrations no longer contains a lie
- Migration runner no longer sees 008 on disk, so nothing to skip
- Live schema unchanged (008 contributed zero)
- Fresh install: 005 + 011 + 20260408_140000 produces identical live schema, no 008 needed

## Lessons Locked

1. Migrations that wrap CREATE TABLE IF NOT EXISTS + ALTER TABLE + CREATE POLICY in a single transaction are a time bomb — if the table was created by a previous migration with different columns, the ALTER/POLICY fails silently.
2. Backfill scripts that insert rows into schema_migrations without verifying the migration actually applied create ghost records that hide failures.
3. Discovery (reading the file + grep for references) should happen before any cleanup migration, not after.

## Remaining Ghosts (Out of Scope)

- 004_taskgraph_columns.sql is in schema_migrations but not in the repo. Flagged as TD-41, deferred to a future cleanup session.

## Cross-References

- docs/STAGE4_DISCOVERY.md — full audit
- brain/db/migrations/20260408_160000_td32_ghost_cleanup.sql — cleanup migration
- brain/db/migrations/005_buddy_events.sql — the real creator
- brain/db/migrations/011_buddy_events_columns.sql — adds source + payload
- brain/db/migrations/20260408_140000_record_buddy_event_fix.sql — priority INTEGER fix
