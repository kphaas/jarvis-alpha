# Alpha Postgres Owner Split Phase 3 Runbook

Generated for the `jarvisbrain` SUPERUSER remediation.

## Current Decision

Phase 3 is split into two steps.

- Phase 3A: create owner/migrator roles and move non-SECURITY-DEFINER ownership.
- Phase 3B: move SECURITY DEFINER functions and demote `jarvisbrain`.

Do not combine these steps. SECURITY DEFINER functions currently run as
`jarvisbrain`; changing that definer role can change RLS behavior.

## Required Gates

Do not run Phase 3A until all are true:

- PR #239 is reviewed and merged.
- Fresh Brain backup exists.
- Brain has a non-`jarvisbrain` superuser recovery role.
- Alpha readiness is green immediately before apply.
- The rollback SQL is present on the operator machine.

Do not run Phase 3B until all Phase 3A postchecks and SECURITY DEFINER
canaries pass.

## Artifacts

- Inventory: `docs/reports/alpha_postgres_ownership_inventory_20260604.md`
- Phase 2 review SQL: `docs/reports/alpha_postgres_owner_split_phase2_20260604.sql`
- Phase 3A apply SQL: `docs/reports/alpha_postgres_owner_split_phase3a_apply_20260604.sql`
- Phase 3A rollback SQL: `docs/reports/alpha_postgres_owner_split_phase3a_rollback_20260604.sql`

## Prechecks

Run on Brain:

```bash
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql \
  -h localhost \
  -U jarvisbrain \
  -d jarvis_alpha \
  -X \
  -v ON_ERROR_STOP=1 \
  -c "SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolcanlogin FROM pg_roles WHERE rolname IN ('jarvisbrain', 'jarvis_pg_breakglass', 'jarvis_alpha_owner', 'jarvis_alpha_migrator') OR rolsuper ORDER BY rolname;"
```

Expected before Phase 3A:

- `jarvis_pg_breakglass` exists and is `rolsuper=true`.
- `jarvisbrain` is `rolsuper=true` and `rolbypassrls=false`.
- `jarvis_alpha_owner` and `jarvis_alpha_migrator` do not exist yet, or already
  match the expected attributes.

Run readiness:

```bash
curl -fskS https://127.0.0.1:8186/health/ready
```

## Phase 3A Apply

Run only after the required gates pass:

```bash
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql \
  -h localhost \
  -U jarvisbrain \
  -d jarvis_alpha \
  -X \
  -v ON_ERROR_STOP=1 \
  -f docs/reports/alpha_postgres_owner_split_phase3a_apply_20260604.sql
```

Phase 3A intentionally does not demote `jarvisbrain`.

## Phase 3A Postchecks

Run the inventory again:

```bash
python scripts/postgres_owner_inventory.py \
  --ssh-target jarvisbrain@jarvis-brain.tail40ed36.ts.net \
  --format markdown \
  --output docs/reports/alpha_postgres_ownership_inventory_after_phase3a.md
```

Expected after Phase 3A:

- `jarvis_alpha_owner` owns the database, relations, extensions, and
  non-SECURITY-DEFINER functions.
- SECURITY DEFINER functions are still held for Phase 3B review.
- `jarvisbrain` is still `rolsuper=true`.

Run Alpha tests and health checks before Phase 3B planning.

## Phase 3A Rollback

Run if Phase 3A causes readiness, migration, or runtime failures:

```bash
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql \
  -h localhost \
  -U jarvisbrain \
  -d jarvis_alpha \
  -X \
  -v ON_ERROR_STOP=1 \
  -f docs/reports/alpha_postgres_owner_split_phase3a_rollback_20260604.sql
```

Then rerun readiness and the inventory.

## Phase 3B Scope

Phase 3B must be a separate review step. It needs canaries for at least:

- approval queue functions
- agent run/event functions
- Buddy memory functions
- message body vault function
- watchdog event function
- secret access function

Only after those canaries pass should the final demotion be considered:

```sql
ALTER ROLE jarvisbrain NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
```
