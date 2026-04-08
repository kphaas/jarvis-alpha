# JARVIS Alpha — Database Baselines

Schema-only snapshots of the `jarvis_alpha` Postgres database. Used as the **source of truth for rebuilding Brain from scratch**.

## Why Baselines Exist

Before April 7, 2026, jarvis_alpha had no migration tracking table. Every migration was applied manually via `psql` with no record of which files ran in what order. This made rebuilding the database from scratch unreliable — you couldn't trust that replaying migrations in alphabetical order would produce the same schema.

Baselines solve this by capturing the **current schema state** as a single SQL file. To rebuild Brain:

1. Restore the baseline (creates all tables, indexes, policies, functions)
2. Apply any post-baseline migrations from `schema_migrations` tracking table

This is the big-tech standard for inherited untracked databases — snapshot the truth, then track forward from there.

## Files

Each baseline date has THREE files:

| File | What | Use |
|---|---|---|
| `baseline_<DATE>_pre_<MILESTONE>.sql` | Schema only, no owners, no privileges, no comments | Reference / diffing |
| `baseline_<DATE>_pre_<MILESTONE>_with_grants.sql` | Schema + grants + RLS policies + ownership | **Rebuild path** — use this one |
| `baseline_<DATE>_pre_<MILESTONE>_globals.sql` | Roles + role memberships from `pg_dumpall --globals-only` | Restore BEFORE the schema dump |

## Naming Convention

```
baseline_YYYY-MM-DD_pre_<milestone>.sql
baseline_YYYY-MM-DD_pre_<milestone>_with_grants.sql
baseline_YYYY-MM-DD_pre_<milestone>_globals.sql
```

The `pre_<milestone>` slug indicates what major change came AFTER this baseline. Examples:
- `pre_step7` — captured before SECURITY DEFINER refactor
- `pre_step6` — captured before FORCE RLS
- `pre_step8` — captured before cost telemetry v2

## When to Regenerate

Capture a fresh baseline:
- Before any large structural change (new tables, RLS policy overhauls, role hierarchy changes)
- After every successful Phase 6 / Phase 7 / Phase 8 deployment
- Quarterly minimum, even if no major changes occurred

## How to Capture a New Baseline

On Brain:
```bash
pg_dump -d jarvis_alpha --schema-only --no-owner --no-privileges --no-comments \
  -f /tmp/baseline_$(date +%Y-%m-%d)_pre_<milestone>.sql

pg_dump -d jarvis_alpha --schema-only \
  -f /tmp/baseline_$(date +%Y-%m-%d)_pre_<milestone>_with_grants.sql

pg_dumpall --globals-only \
  -f /tmp/baseline_$(date +%Y-%m-%d)_pre_<milestone>_globals.sql
```

On Air:
```bash
scp jarvisbrain@100.64.166.22:/tmp/baseline_*.sql ~/jarvis-alpha/db/baselines/
```

Then commit via `jarvisalpha_commit.sh`.

## Rebuild Procedure (Disaster Recovery)

If Brain Postgres is destroyed and needs full rebuild:

```bash
# 1. Restore globals (creates roles)
psql -U postgres -f db/baselines/baseline_<LATEST>_globals.sql

# 2. Create empty database
createdb jarvis_alpha

# 3. Restore baseline schema with grants
psql -d jarvis_alpha -f db/baselines/baseline_<LATEST>_with_grants.sql

# 4. Apply post-baseline migrations from canonical dir
bash ~/jarvis-alpha/scripts/apply_migrations.sh

# 5. Verify
psql -d jarvis_alpha -c "SELECT COUNT(*) FROM schema_migrations;"
psql -d jarvis_alpha -c "\dt"
```

## What's NOT in a Baseline

- **Data** — baselines are schema only. Data must be restored from backups separately.
- **Logical replication slots** — recreated on demand
- **Statistics / `ANALYZE` data** — Postgres regenerates automatically
- **Connection state** — irrelevant

## Versioning

Baselines are committed to git alongside the migrations they snapshot. The git commit message should reference which migration created the new state being baselined.
