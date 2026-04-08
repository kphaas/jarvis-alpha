# JARVIS Alpha — Database Migrations

This is the **canonical** migration directory for the `jarvis_alpha` Postgres database.

## Status

- **Live since:** April 2026
- **Database:** `jarvis_alpha` on Brain (Mac Studio M2 Ultra)
- **Postgres version:** 16.13 (Homebrew)
- **Tracking table:** `schema_migrations`
- **Runner:** `~/jarvis-alpha/scripts/apply_migrations.sh`

## Rules — Non-Negotiable

1. **One canonical directory.** All future migrations land here. No subdirectories. No parallel migration trees anywhere in the repo.
2. **Filenames are immutable.** Once a migration is committed and applied, its filename and content are frozen. The runner enforces this via SHA-256 checksums in the `schema_migrations` table.
3. **Never edit an applied migration.** If you need to fix something, write a new migration. Editing an applied file will cause the runner to refuse to start until the checksum matches or the row is manually corrected.
4. **One file per logical change.** No multi-purpose migrations. Smaller files = clearer history + easier review.
5. **Idempotent where possible.** Use `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, `DROP TABLE IF EXISTS`, etc. The baseline snapshot in `db/baselines/` is the rebuild path, not migration replay — but idempotency catches accidental double-applies.
6. **Wrap in `BEGIN; ... COMMIT;`** for any migration with multiple statements. The runner applies one file per transaction, but explicit transactions are clearer.

## Naming Conventions

### Historical files (003 through 015 + the moved 004/007/008/009/010/011/012)
**Frozen.** Never renumbered, never renamed. Lexically sorted by filename.

### New files (going forward)
Use timestamp prefixes:

```
YYYYMMDD_HHMMSS_short_slug.sql
```

Example: `20260408_143000_create_writer_role.sql`

Why timestamps:
- No collision risk between parallel work
- Lexically sortable and obvious to humans
- Sorts AFTER the legacy zero-padded numeric files (because `2` > `0`)
- No renumbering pressure ever

## Workflow

### Adding a new migration

1. Create file: `brain/db/migrations/YYYYMMDD_HHMMSS_<slug>.sql`
2. Write SQL — wrap in `BEGIN; ... COMMIT;` if multi-statement
3. Test on a scratch DB if possible
4. Run the runner: `bash ~/jarvis-alpha/scripts/apply_migrations.sh`
5. Verify it appears in `schema_migrations` table on Brain
6. Commit and push via `bash ~/jarvis-alpha/scripts/jarvisalpha_commit.sh "msg"`

### Rebuilding Brain from scratch

1. Restore globals: `psql -f db/baselines/baseline_<DATE>_pre_step7_globals.sql`
2. Create empty `jarvis_alpha` database
3. Restore baseline schema: `psql -d jarvis_alpha -f db/baselines/baseline_<DATE>_pre_step7_with_grants.sql`
4. Run apply_migrations.sh to apply any post-baseline migrations
5. Verify by querying `schema_migrations` table

The baseline is the source of truth for rebuild — NOT migration replay from 003.

## Historical Context

Prior to April 7, 2026 there were THREE migration systems coexisting:

- `db/alembic/versions/` — Alembic Python migrations (3 files, used briefly in March)
- `brain/db/migrations/` — Raw SQL files numbered 003+
- `brain/migrations/` — Raw SQL files added in April sessions, never tracked

All three were applied manually via `psql`, with no tracking table, no checksums, no runner.

On April 7, 2026 we consolidated into this directory:
- Moved all 8 files from `brain/migrations/` here (preserving filenames)
- Deleted `brain/migrations/`
- Marked `db/alembic/` as deprecated
- Created `schema_migrations` tracking table
- Built `apply_migrations.sh` runner
- Backfilled all 23 historical files into `schema_migrations` with `source = 'pre-tracking'`
- Captured baseline schema dump in `db/baselines/`

This README is the post-cleanup standard.

## Duplicate Numbers (Historical)

Some legacy files share the same numeric prefix because they were authored in parallel sessions before the consolidation:

- `007_honeypot_events.sql`, `007_node_registry.sql`, `007_prompt_registry.sql`
- `008_buddy_events.sql`, `008_dream_mode.sql`, `008_fix_gateway_health_url.sql`, `008b_task_events.sql`

These are frozen. Lexical sort handles ordering. New files use timestamp prefixes specifically to prevent this from happening again.
