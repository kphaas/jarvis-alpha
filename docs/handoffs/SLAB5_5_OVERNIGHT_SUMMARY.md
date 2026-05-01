# SLAB 5.5 — Overnight Scaffolding Summary

**Generated:** 2026-05-01 (overnight prep)
**Scope:** Test infrastructure for the RLS smoke harness — files only.
**Database state:** unchanged. Nothing was applied. Ken applies in the morning.

---

## What I wrote

| # | File | Lines | Purpose |
|---|---|---|---|
| 1 | `brain/db/tests/test_data_setup.sql` | 180 | Idempotent seed: 4 users, 1 workspace, 2 chat threads, 4 chat messages |
| 2 | `brain/db/tests/rls_smoke.sql` | 187 | 8-case smoke harness (Slab 3 Q7 / Slab 5 deliverable 3) |
| 3 | `scripts/run_smoke.sh` | 138 | Bash wrapper — refuses any target other than `test`, logs to `/tmp/rls_smoke_<ts>.log` |
| 4 | `docs/handoffs/SLAB5_5_OVERNIGHT_SUMMARY.md` | (this file) | Handoff |

`scripts/run_smoke.sh` was made executable (`chmod +x`).
Directory `brain/db/tests/` was created (did not previously exist).

`bash -n` against `run_smoke.sh` passes — no syntax errors.

---

## Schema discovery (where each table came from)

Source files inspected:
- `brain/db/schema.sql` — alpha_users, alpha_workspaces, alpha_workspace_users
- `db/postgres_schema.sql` — alpha_buddy_events, alpha_conversation_memory, alpha_task_events
- `db/baselines/baseline_2026-04-07_pre_step7.sql` — chat_threads, chat_messages
- `brain/db/migrations/009_child_profiles.sql` — content_rating columns + child policies
- `brain/db/migrations/013_workspace_seeding.sql` — alpha_users projection from alpha_profiles
- `brain/db/migrations/015_chat_rls_fix.sql` — current chat_threads / chat_messages policies
- `brain/db/migrations/20260430_160900_slab2_guc_namespace_migration.sql` — confirmed `app.*` / `jarvis.*` GUC keys were renamed to `rls.*` in Slab 2

Key column types confirmed (and used in the seed):
- `alpha_users.id` — TEXT (not UUID). Stores UUID-formatted strings as text.
- `alpha_workspaces.id` — TEXT.
- `alpha_workspace_users` — composite PK on `(workspace_id, user_id)`, FKs to `alpha_users(id)` and `alpha_workspaces(id)`.
- `chat_threads.id` UUID; `chat_threads.user_id` TEXT.
- `chat_messages.id` UUID; `chat_messages.thread_id` UUID FK to `chat_threads(id)`.
- `chat_threads.content_rating`, `chat_messages.content_rating`, `alpha_conversation_memory.content_rating` — TEXT with CHECK in `('all_ages','age_8_plus','teen','adult')`.
- `chat_messages.role` — TEXT with CHECK in `('user','assistant','system')`.

---

## Schema assumptions Ken should verify

1. **`alpha_users.id` is TEXT, not UUID.** The user task asked for "UUIDs" but the column is TEXT. UUID-formatted strings (`'00000000-0000-0000-0000-000000000001'` etc.) are stored as TEXT. Existing canonical Shape A template (Slab 3) casts the GUC `rls.user_id` to `::uuid` — production `chat_threads.user_id` is also TEXT and the **active** policy (`015_chat_rls_fix.sql`) compares as TEXT (no cast). So the seeded values match correctly today; Slab 6 may need to reconcile this when migrating to canonical Shape A.

2. **`alpha_users.role` has no CHECK constraint** (verified — only PK and email UNIQUE). I inserted `'platform_admin'`, `'user'`, `'child'` per spec, even though the schema default is `'workspace_user'`. RLS policies read role from the `rls.role` GUC, not from this column, so the column value is metadata only.

3. **`alpha_users.max_rating` does not exist.** The user spec said `max_rating=age_8_plus` for the child user. There is no such column in `alpha_users`. The `max_rating` value is a **session GUC** (`rls.max_rating`) set per-session by the smoke harness, not a row attribute. The child fixture sets `is_child=true` and `child_age=8` instead — this matches the `alpha_profiles` row Ken already has for Ryleigh.

4. **`chat_threads.owner_profile`** is a FK to `alpha_profiles(id)`. I left it NULL on test rows to avoid pulling the alpha_profiles fixture chain into Slab 5.5. The column is nullable, so this is valid; if a child-profile-aware test is added later, the alpha_profiles seed row will need to be added too.

5. **`chat_threads.user_id` has no FK constraint** to `alpha_users(id)` (verified in baseline). If a FK is later added, the seed values still work because the four user IDs are inserted first.

6. **psql path** in `scripts/run_smoke.sh` is hardcoded to `/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql` per spec. This is the Brain path; it does NOT exist on the laptop where I ran the scaffolding. This is expected — the script is intended to run on Brain.

---

## TODOs / unknowns surfaced (none blocking)

- The current `child_thread_isolation` policy from `009_child_profiles.sql` (rewritten by Slab 2 to use `rls.*` GUCs) still uses the literal role string `'admin'`, not the canonical `'platform_admin'`. **This is exactly the class of bug Slab 5 deliverable 2 fixes for `alpha_task_events`.** Case 1 in the smoke harness expects `platform_admin` to see all `chat_threads` rows. With today's policy text, Case 1 may fail until Slab 6 rewrites chat_threads to canonical Shape A. **This is the smoke harness doing its job** — it surfaces the gap. Ken will see one or more `Case N FAIL` messages and that's a feature, not a defect in the harness.
- The smoke harness uses `alpha_buddy_events` for Shape B (cases 5 & 6). If Shape B test rows are needed for richer assertions, they'd need to be seeded by a SECDEF-wrapped insert because Shape B's PERMISSIVE policy only admits `platform_admin`. Today's seed leaves Shape B empty; case 6 only asserts `n >= 0` (admin path doesn't error) which is fine.
- No `alpha_conversation_memory` seed rows are inserted. Case 3 asserts `count(*) WHERE content_rating IN ('teen','adult') = 0`, which trivially passes on an empty table. If Ken wants Case 3 to be meaningful, add 2-3 alpha_conversation_memory rows (one with `content_rating='all_ages'`, one with `'teen'`, one with `'adult'`) to `test_data_setup.sql` — but this requires a workable insert path through the table's RLS policies. Defer to morning conversation.

---

## Recommended morning sequence

In order:

1. **Read the three new files top to bottom** (≈ 3 min):
   - `brain/db/tests/test_data_setup.sql`
   - `brain/db/tests/rls_smoke.sql`
   - `scripts/run_smoke.sh`
2. **Decide on UUID-vs-TEXT** for `alpha_users.id` and `chat_threads.user_id`. Slab 6 will revisit, but confirm the seed is acceptable for today.
3. **Create the test database manually** (this script intentionally does NOT do this):
   ```sql
   CREATE DATABASE jarvis_alpha_test;
   ```
   Then apply the migrations to it (the existing `apply_migrations.sh` is hardcoded to `jarvis_alpha`; you may want a separate one-off `psql -d jarvis_alpha_test -f <each migration>`, or temporarily override `DB=` at the top of `apply_migrations.sh`).
4. **Run the smoke harness** from Brain:
   ```bash
   bash scripts/run_smoke.sh test
   # tail -f /tmp/rls_smoke_<timestamp>.log in another tab if you like
   ```
5. **Read failures as features.** Any `Case N FAIL` is the harness telling you a policy is non-canonical. Before Slab 6 starts, decide which failures are expected (e.g. `chat_threads` admin literal `'admin'` not `'platform_admin'`) vs. surprising.
6. **Optional:** add Shape B / `alpha_conversation_memory` fixtures if you want Cases 3 and 6 to be more than smoke. Today they pass trivially.
7. **Do NOT commit yet.** Spec says Ken reviews everything first.

---

## Files NOT touched (per spec)

- No changes to `brain/db/migrations/` (only read).
- No changes to `executor.py`, `dream_planning.py`, or any production code.
- No changes to `pyproject.toml`.
- No DB connections, no `CREATE DATABASE`, no migration runs.
- No commits.

---

## Cross-references

- `docs/SLAB3_POLICY_TEMPLATE.md` — Shape A / A-FK / B canonical templates + Q7 smoke matrix
- `docs/SLAB5_BUG_FIXES_SPEC.md` — Deliverable 3 (the 8 cases mirrored here)
- `brain/db/migrations/015_chat_rls_fix.sql` — currently active chat_threads / chat_messages policies
- `brain/db/migrations/20260430_160900_slab2_guc_namespace_migration.sql` — confirms `rls.*` is the live GUC namespace

---

## Bugs surfaced by harness run

The Round 1 harness run (overnight, 2026-05-01) executed end-to-end and surfaced two issues:

- **TD-196 (P0 for Slab 6)** — `chat_threads_isolation` policy is defined as
  `user_id = current_setting('rls.user_id', true)` with **no admin override clause**.
  Under canonical Shape A, `platform_admin` should be allowed to see all rows;
  with the current policy text, an admin session sees only rows whose `user_id`
  literally equals the admin's `rls.user_id`. This needs to be rewritten to
  canonical Shape A in Slab 6 (mirror the pattern used by `015_chat_rls_fix.sql`
  but add the `OR rls.role = 'platform_admin'` admin-override clause).
  *Owner:* Ken / Slab 6.

- **Harness false-pass (fixed in Round 2)** — the Round 1 run used DB user
  `jarvisbrain`, which owns the alpha tables. Postgres bypasses RLS for table
  owners by default (no `FORCE ROW LEVEL SECURITY` is set), so policies were
  never actually evaluated and Case 1 falsely reported PASS even with the
  TD-196 bug present. Round 2 introduces a non-owner role
  (`jarvis_alpha_smoke`, `NOBYPASSRLS`) that the harness now runs under, so
  RLS enforcement is real and Case 1 will correctly surface TD-196 on the
  next run.

---

## Round 2 fix

**What changed (2026-05-01, Round 2):**

1. **New file: `brain/db/tests/test_role_setup.sql`**
   - Idempotently creates role `jarvis_alpha_smoke` with `LOGIN NOSUPERUSER NOBYPASSRLS`
     via a `DO $$ ... EXCEPTION WHEN duplicate_object ...` block.
   - Re-asserts the attributes via `ALTER ROLE` (defends against a pre-existing
     role created with different flags).
   - Grants `USAGE` on schema `public` and `SELECT, INSERT, UPDATE, DELETE` on
     all tables in `public`, plus `USAGE, SELECT` on all sequences.
   - Adds `ALTER DEFAULT PRIVILEGES FOR ROLE jarvisbrain` so future tables created
     by the owner stay reachable without re-running the script.
   - Wrapped in `BEGIN; ... COMMIT;`.

2. **Modified `scripts/run_smoke.sh`** — three steps now, not two:
   - Step 1: `test_role_setup.sql` as `jarvisbrain` (owner; can `CREATE ROLE`).
   - Step 2: `test_data_setup.sql` as `jarvisbrain` (owner; needs `INSERT`
     and bypasses RLS during seeding so `ON CONFLICT DO NOTHING` works
     against rows the smoke role couldn't see).
   - Step 3: `rls_smoke.sql` as `jarvis_alpha_smoke` via `-U jarvis_alpha_smoke`
     (non-owner; RLS is genuinely enforced).
   - Banner, usage text, and per-step status messages updated to reflect the
     new sequence and which role each step runs under.
   - Existing `"test"` target check, `/tmp/rls_smoke_<ts>.log` tee'ing,
     `ON_ERROR_STOP=1`, and `chmod +x` on the wrapper are all preserved.

3. **Updated this handoff** — added the "Bugs surfaced by harness run" section
   above (TD-196 captured for Slab 6, plus a note that the harness now enforces
   RLS for real).

**Verified locally:**
- `bash -n scripts/run_smoke.sh` → exit 0 (no syntax errors).
- `scripts/run_smoke.sh` mode is still `-rwxr-xr-x` (executable bit preserved).
- `brain/db/tests/test_role_setup.sql` is well-formed: `BEGIN;` / `COMMIT;`
  at the outer level, `DO $$ ... $$` block uses correct
  `duplicate_object` exception class for `CREATE ROLE` idempotency.

**Assumptions Ken should sanity-check:**

1. **Role name `jarvis_alpha_smoke`** is not already in use for something
   else on Brain. If it is, the `ALTER ROLE` in step 1 will silently flip its
   attributes — review before applying.
2. **`jarvisbrain` owns the role-creation privilege.** The script does
   `psql -U jarvisbrain -f test_role_setup.sql`, which requires `jarvisbrain`
   to have `CREATEROLE` (or be a superuser). If that's not true on Brain, run
   `test_role_setup.sql` once as a superuser by hand and the script will
   no-op on subsequent runs (the `EXCEPTION WHEN duplicate_object` swallows
   the create attempt).
3. **Seeding still as owner is intentional.** `test_data_setup.sql` was not
   modified per spec. Running it as the non-owner would require the smoke
   role to satisfy the `WITH CHECK` clauses of every policy on every seeded
   table, which defeats the purpose of seeding. Owner-bypass during seed +
   non-owner during the smoke is the standard split.
4. **`ALL TABLES IN SCHEMA public`** grants apply to the tables that exist at
   the moment the script runs. `ALTER DEFAULT PRIVILEGES FOR ROLE jarvisbrain`
   covers tables `jarvisbrain` creates afterward; if migrations are ever
   applied as a different role, re-run `test_role_setup.sql` so the new
   tables are reachable by the smoke role.
5. **No DB connections were made** by this Round 2 work — only file edits.
   Nothing to roll back. Ken still applies on Brain.
