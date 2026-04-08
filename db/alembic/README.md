# DEPRECATED — Alembic Migrations

**Status:** Deprecated as of April 7, 2026. Do not use. Do not modify.

## What This Is

An early attempt at using SQLAlchemy/Alembic for database migrations. Three migrations were applied to `jarvis_alpha` via this system in early April 2026:

- `001_taskgraph.py`
- `002_restore_task_events_fk.py`
- `003_chat_threads.py`

## Why It's Deprecated

The single-developer workflow, RLS-heavy schema, and need for explicit SQL control made Alembic a poor fit. Raw SQL migrations with a tracking table and bash runner are the canonical system going forward.

See `brain/db/migrations/README.md` for the current migration system.

## Why We Keep These Files

1. **Git history reference** — these are the original schema for `alpha_task_graphs`, `alpha_task_events`, `chat_threads`, and `chat_messages`. Useful for forensic understanding of column origins.
2. **No safe way to delete** — the schema they created is in production. Removing the files doesn't remove the schema.

## What Got Cleaned Up

- `alembic_version` table on Brain was DROPPED on April 7, 2026 as part of the migration system consolidation. Alembic CLI commands will fail against the live database — that's intentional.
- `alembic.ini` at the repo root remains for historical reference but is not used by any active tooling.

## Do Not

- Run `alembic upgrade` against `jarvis_alpha`
- Add new migrations here
- Edit existing files in this directory
- Re-introduce the `alembic_version` table

## If You Need Schema Changes

Use the canonical migration system:

```
~/jarvis-alpha/brain/db/migrations/
```

See its README for the current workflow.
