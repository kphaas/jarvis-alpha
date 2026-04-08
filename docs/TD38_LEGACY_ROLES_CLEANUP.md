# TD-38: Legacy Roles Cleanup — Forward Plan

**Status:** PARTIAL — defensive actions in Step 6.5 Stage 2, full cleanup deferred.
**Audit:** docs/TD38_LEGACY_ROLES_AUDIT.md
**Updated:** 2026-04-08 (corrected after finding jarvis is production)

## Correction to Audit

Initial audit flagged `jarvis` as dead. WRONG. The `jarvis` role is actively used by `~/jarvis/backups/postgres/weekly_basebackup.sh` (Sunday 02:00 cron) for pg_basebackup to Unraid. Last successful run: 2026-04-05. `jarvis_app` is still dead.

## What Stage 2 Did

1. Explicit `GRANT USAGE ON SCHEMA public TO jarvis, jarvis_app` before REVOKE
2. `ALTER ROLE jarvis NOBYPASSRLS` — safe because pg_basebackup uses REPLICATION privilege, not RLS
3. No drops, no basebackup changes

## What Still Needs to Happen

### Before Stage 5
- [x] Comment out dead `pg_dump -U jarvis jarvis` cron (done 2026-04-08)
- [ ] Verify Sunday basebackup still runs successfully after NOBYPASSRLS change

### TD-39 (new, low priority)
- [ ] Migrate `weekly_basebackup.sh` to use `jarvisbrain` instead of `jarvis`
- [ ] Then `jarvis` role becomes droppable

### After Stage 5 + TD-39 complete
- [ ] `DROP ROLE jarvis_app` (no dependencies, safe anytime)
- [ ] `DROP ROLE jarvis` (only after basebackup migrated to jarvisbrain)

## Do NOT
- Drop `jarvis` before migrating basebackup script
- Touch `weekly_basebackup.sh` in Stage 2

## Cross-References
- docs/TD38_LEGACY_ROLES_AUDIT.md
- brain/db/migrations/20260408_120000_jarvis_alpha_writer_role.sql
- ~/jarvis/backups/postgres/weekly_basebackup.sh (Brain, not in repo)
