# STAGE4_DISCOVERY.md — TD-32 Pre-Deletion Audit for 008_buddy_events.sql

## Summary

**SAFE TO DELETE 008_buddy_events.sql.** Live schema is entirely explained by the 005 lineage. The 008 `CREATE TABLE IF NOT EXISTS` was a no-op (table already existed). No migration or application code references 008's dead columns (`graph_id`, `step_id`, `message` on `alpha_buddy_events`) or its `buddy_events_isolation` policy. The runner already skips the file permanently via the ghost record in `schema_migrations`.

---

## Task 1 — Which migration creates alpha_buddy_events

**Two files contain `CREATE TABLE IF NOT EXISTS alpha_buddy_events`:**

### `brain/db/migrations/005_buddy_events.sql` (line 1) — THE REAL ONE

```sql
CREATE TABLE IF NOT EXISTS alpha_buddy_events (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    TEXT,
  event_type TEXT NOT NULL CHECK (
    event_type IN ('alert','reminder','suggestion','system')
  ),
  title      TEXT NOT NULL,
  body       TEXT,
  priority   INT NOT NULL DEFAULT 2,
  read       BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_buddy_events_user
  ON alpha_buddy_events (user_id, read, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_buddy_events_unread
  ON alpha_buddy_events (read, created_at DESC)
  WHERE read = false;
```

This matches the live schema. Columns: `id UUID`, `user_id TEXT`, `event_type TEXT` (CHECK: alert|reminder|suggestion|system), `title TEXT`, `body TEXT`, `priority INT DEFAULT 2`, `read BOOLEAN`, `created_at TIMESTAMPTZ`. No RLS, no FKs.

### `brain/db/migrations/008_buddy_events.sql` (line 6) — THE DEAD ONE

```sql
CREATE TABLE IF NOT EXISTS alpha_buddy_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type  TEXT NOT NULL
        CHECK (event_type IN (
            'graph_complete', 'graph_halted', 'step_failed',
            'step_retrying', 'ci_required', 'approval_required'
        )),
    graph_id    UUID NOT NULL REFERENCES alpha_task_graphs(id) ON DELETE CASCADE,
    step_id     UUID REFERENCES alpha_task_steps(id) ON DELETE SET NULL,
    message     TEXT NOT NULL,
    priority    TEXT NOT NULL DEFAULT 'normal'
        CHECK (priority IN ('low', 'normal', 'high', 'critical')),
    read        BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

This definition is incompatible with live schema: different `event_type` values, adds `graph_id`/`step_id`/`message`, uses `TEXT` priority instead of `INT`. Because 005 already ran, the `IF NOT EXISTS` guard made this a **complete no-op**. The table was never replaced with the 008 shape.

**Conclusion:** `005_buddy_events.sql` is the real CREATE that built the live table.

---

## Task 2 — Which migrations alter alpha_buddy_events

**Two hits only:**

| File | Line | Statement |
|------|------|-----------|
| `008_buddy_events.sql` | 32 | `ALTER TABLE alpha_buddy_events ENABLE ROW LEVEL SECURITY;` |
| `011_buddy_events_columns.sql` | 1 | `ALTER TABLE alpha_buddy_events ADD COLUMN IF NOT EXISTS source TEXT;` |
| `011_buddy_events_columns.sql` | 2 | `ALTER TABLE alpha_buddy_events ADD COLUMN IF NOT EXISTS payload JSONB;` |

**008 ALTER:** The `ENABLE ROW LEVEL SECURITY` is inside `008_buddy_events.sql` which was wrapped in a `BEGIN`/`COMMIT` transaction. Per the STEP6_5_PREFLIGHT.md analysis (§4), this transaction rolled back (dead-on-arrival). RLS is currently **disabled** on `alpha_buddy_events`.

**011 ALTER:** `011_buddy_events_columns.sql` adds `source TEXT` and `payload JSONB` using `ADD COLUMN IF NOT EXISTS` — idempotent and compatible with the 005-shape table.

---

## Task 3 — Live schema vs migration history (column by column)

Live schema columns: `id, user_id, event_type, title, body, priority, read, created_at, source, payload`

| Column | Type (live) | Created by | Modified by | Notes |
|--------|-------------|------------|-------------|-------|
| `id` | UUID PK | `005_buddy_events.sql:2` | — | `gen_random_uuid()` default |
| `user_id` | TEXT | `005_buddy_events.sql:3` | — | Nullable |
| `event_type` | TEXT NOT NULL | `005_buddy_events.sql:4-6` | — | CHECK: alert\|reminder\|suggestion\|system |
| `title` | TEXT NOT NULL | `005_buddy_events.sql:7` | — | |
| `body` | TEXT | `005_buddy_events.sql:8` | — | Nullable |
| `priority` | INT NOT NULL DEFAULT 2 | `005_buddy_events.sql:9` | `20260408_140000_record_buddy_event_fix.sql` confirms INTEGER | 008 defined this as TEXT — never applied |
| `read` | BOOLEAN NOT NULL DEFAULT false | `005_buddy_events.sql:10` | — | |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | `005_buddy_events.sql:11` | — | |
| `source` | TEXT | `011_buddy_events_columns.sql:1` | — | Added post-005 |
| `payload` | JSONB | `011_buddy_events_columns.sql:2` | — | Added post-005 |

**All 10 live columns are fully accounted for by 005 + 011. Zero columns come from 008.**

`priority INTEGER` confirmed: migration `20260408_140000_record_buddy_event_fix.sql` explicitly documents "Schema reality: priority INTEGER (not TEXT)" and corrects the `record_buddy_event` function signature to `p_priority INTEGER`. This contradicts 008's `priority TEXT` definition, further proving 008's schema was never in effect.

---

## Task 4 — References to 008's dead columns in other migrations

Searched `brain/db/migrations/` for each dead pattern:

| Pattern | Result |
|---------|--------|
| `graph_id.*alpha_buddy_events` | **1 hit** — `008_buddy_events.sql:30` only (index on 008's own graph_id) |
| `alpha_buddy_events.*graph_id` | No hits outside 008 |
| `step_id.*alpha_buddy_events` | **No hits** |
| `alpha_buddy_events.*step_id` | **No hits** |
| `message.*alpha_buddy_events` | **No hits** |
| `alpha_buddy_events.*message` | **No hits** |
| `buddy_events_isolation` | **1 hit** — `008_buddy_events.sql:34` only |

**Verdict:** The `graph_id` index reference is self-contained within 008. No other migration uses any of 008's dead columns or its policy. **Zero external dependencies on 008's design in the migration chain.**

---

## Task 5 — Code references to 008's dead design

Searched `brain/**/*.py` (excluding `.venv`, `__pycache__`, `.pyc`):

| Pattern | Result |
|---------|--------|
| `graph_id.*buddy` (in Python) | **No hits** |
| `buddy.*graph_id` (in Python) | **No hits** |
| `step_id.*buddy` (in Python) | **No hits** |
| `buddy.*step_id` (in Python) | **No hits** |
| `buddy_events.*graph` (in Python) | **No hits** |
| `buddy_events_isolation` (all files) | **1 hit** — `008_buddy_events.sql:34` only |

**Important clarification on `graph_id`/`step_id` in Python code:**

`brain/tasks/executor.py:497-498` and `brain/tasks/watchdog.py:112` do contain INSERTs with `graph_id, step_id, message, priority` — but these write to `alpha_task_events`, **not** `alpha_buddy_events`. (Confirmed at executor.py:497 and watchdog.py:111.)

`brain/routes/buddy.py` reads/writes `alpha_buddy_events` using only the live columns: `id, user_id, event_type, title, body, priority, read, created_at` (lines 41-44). No reference to `graph_id`, `step_id`, or `message`.

The `record_buddy_event` SECURITY DEFINER function (`20260408_140000_record_buddy_event_fix.sql`) INSERTs into `alpha_buddy_events` with columns `(user_id, event_type, title, body, priority, source, payload)` — all live-schema columns, zero dead columns.

**Verdict: No application code references 008's dead design against alpha_buddy_events.**

---

## Task 6 — References to 008 file itself

Searched `brain/`, `scripts/`, and `docs/` for `008_buddy_events`:

| File | Line | Context |
|------|------|---------|
| `docs/STEP6_5_PREFLIGHT.md` | 157, 164, 189, 192, 197, 200, 379, 416, 437 | Historical analysis only — documents the conflict, recommends deletion |
| `docs/STEP7_DISCOVERY.md` | 114, 128, 204, 206, 208, 405, 407, 409, 426 | Historical audit notes only |
| `docs/PATTERNS.md` | 467 | Documents `buddy_events_isolation` as a known policy (from migration definition) |
| `brain/db/migrations/README.md` | 89 | Lists 008_buddy_events.sql under "Duplicate Numbers (Historical)" — frozen |
| `brain/db/migrations/008_buddy_events.sql` | 1 | Self-reference (comment header) |
| `brain/db/migrations/20260408_011144_backfill_schema_migrations.sql` | 24 | Inserts ghost record into schema_migrations |

**What breaks if we delete 008_buddy_events.sql:**

1. **`docs/STEP6_5_PREFLIGHT.md` / `docs/STEP7_DISCOVERY.md`** — Documentation references a now-absent file. These are historical audit docs. No functional impact.
2. **`docs/PATTERNS.md:467`** — References `buddy_events_isolation` policy which was never actually applied. Entry should be removed as part of Stage 4 cleanup. No functional impact.
3. **`brain/db/migrations/README.md:89`** — Lists the file under "Historical." Should be removed. No functional impact.
4. **`brain/db/migrations/20260408_011144_backfill_schema_migrations.sql:24`** — Inserts a ghost record for `008_buddy_events.sql` into `schema_migrations`. If 008 is deleted, this line inserts a tracking record for a file that no longer exists. The runner iterates `*.sql` files — it only checks files it finds on disk. A schema_migrations record for a deleted file is **harmless orphan data** — the runner never encounters it. No functional impact on migration execution.

**No functional code (scripts, Python, migration runner) breaks if 008_buddy_events.sql is deleted.**

---

## Task 7 — Dependent buddy migrations

**All migrations containing "buddy" or referencing alpha_buddy_events:**

### `005_buddy_events.sql`
- **What it does:** Creates `alpha_buddy_events` with live schema. Creates 2 indexes.
- **Depends on 008?** No — runs before 008 in lexical order.
- **Works against live schema?** Yes — this IS the creator of the live schema.

### `008_buddy_events.sql`
- **What it does:** Attempts to CREATE TABLE IF NOT EXISTS with dead schema (no-op), adds RLS (rolled back), creates `buddy_events_isolation` policy (rolled back).
- **Depends on anything?** Declares FK to `alpha_task_graphs` and `alpha_task_steps` — those tables existed but the IF NOT EXISTS guard prevented this from ever executing.
- **Works against live schema?** Irrelevant — it was a no-op. Deleting it changes nothing.

### `011_buddy_events_columns.sql`
- **What it does:** `ADD COLUMN IF NOT EXISTS source TEXT` and `ADD COLUMN IF NOT EXISTS payload JSONB`.
- **Depends on 008?** No — depends only on the table existing (from 005). Uses `IF NOT EXISTS` guards.
- **Works against live schema?** Yes — idempotent, adds columns that already exist.

### `20260408_130000_security_definer_functions.sql`
- **What it does:** Creates `record_buddy_event(TEXT×6, JSONB) RETURNS BIGINT` — a SECURITY DEFINER function that INSERTs into `alpha_buddy_events`. (Note: This was superseded by the next migration.)
- **Depends on 008?** No — uses live-schema columns only.
- **Works against live schema?** Partially — had wrong return type (BIGINT vs UUID) and wrong priority type (TEXT vs INT). Superseded.

### `20260408_140000_record_buddy_event_fix.sql`
- **What it does:** DROPs old `record_buddy_event` signature, recreates with correct types: `p_priority INTEGER`, returns `UUID`. Grants to `jarvis_alpha_writer` and `jarvisbrain`.
- **Depends on 008?** No — depends on live schema (005 + 011) shape.
- **Works against live schema?** Yes — fully aligned with live schema columns and types.

**No buddy migration depends on 008 having run. The 005 → 011 → 20260408_140000 chain is self-consistent and 008-independent.**

---

## Stage 4 Go/No-Go Verdict

**SAFE TO DELETE `008_buddy_events.sql`.**

Evidence:

1. **008's CREATE was a no-op.** `005_buddy_events.sql` already created `alpha_buddy_events`. The `IF NOT EXISTS` guard in 008 prevented any schema change.
2. **008's ALTER/POLICY never applied.** The `BEGIN`/`COMMIT` transaction rolled back (per prior analysis in STEP6_5_PREFLIGHT.md §4). RLS is currently disabled on `alpha_buddy_events`.
3. **No migration references 008's dead columns.** Zero hits for `graph_id`, `step_id`, or `message` in the context of `alpha_buddy_events` outside 008 itself.
4. **No application code references 008's dead design.** All Python code writing to `alpha_buddy_events` uses 005-lineage columns.
5. **The migration runner already skips 008.** Ghost record in `schema_migrations` (applied_at IS NULL, backfilled) with correct checksum means the runner sees filename present + checksum matches → skip. Deleting the file removes it from the runner's iteration loop — the orphaned schema_migrations record is harmless.
6. **`buddy_events_isolation` policy only exists in 008.** Since it never applied (transaction rollback), removing the file removes the last reference to this dead policy.

**Recommended cleanup alongside file deletion:**
- Remove `008_buddy_events.sql` entry from `brain/db/migrations/README.md` (line 89)
- Remove `buddy_events_isolation` stale entry from `docs/PATTERNS.md` (line 467)
- Optionally delete the orphaned ghost row from `schema_migrations` (not required for correctness)

---

## Fresh-Install Impact Assessment

### Current runner behavior on fresh DB:

The runner (`apply_migrations.sh`) requires `schema_migrations` to exist before it starts. A fresh install sequence is:

1. Manually apply `20260408_011144_create_schema_migrations.sql` — creates the tracking table
2. Manually apply `20260408_011144_backfill_schema_migrations.sql` — inserts ghost records for ALL historical files (including 008_buddy_events.sql) with `applied_at = NULL`
3. Run `apply_migrations.sh` — for each `*.sql` file it finds, checks schema_migrations → finds existing checksum record → skips

**Result of current fresh install:** The runner skips ALL historical migrations because the backfill inserted tracking records for them. The database ends up with only the `schema_migrations` table and no application schema. This is a pre-existing issue independent of Stage 4.

### After deleting `008_buddy_events.sql`:

- The backfill migration (`20260408_011144_backfill_schema_migrations.sql:24`) still inserts a ghost record for `008_buddy_events.sql`. This is harmless — the runner never iterates over a file that doesn't exist.
- The runner's loop skips 008 (no file on disk) just as it does today (file present but runner sees ghost record and skips).
- Fresh install behavior is **identical** before and after deletion of 008.

### Correct migration sequence for live schema (if applied without pre-existing schema_migrations ghost records):

```
003_memory_tiers.sql
004_dev_agent.sql
004_vector_768.sql
005_buddy_events.sql          ← Creates alpha_buddy_events (live shape)
006_task_graphs.sql
007_honeypot_events.sql
007_node_registry.sql
007_prompt_registry.sql
[008_buddy_events.sql]        ← NO-OP (IF NOT EXISTS guard, table already exists)
008_dream_mode.sql
008_fix_gateway_health_url.sql
008b_task_events.sql
009_child_profiles.sql
009_cost_center.sql
010_approval_gateway.sql
010_cost_tracking.sql
011_buddy_events_columns.sql  ← Adds source, payload columns
011_power_tracking.sql
012_alpha_briefings.sql
012_watchdog_events.sql
013_workspace_seeding.sql
014_vault_rls_v1.sql
015_chat_rls_fix.sql
20260408_011144_create_schema_migrations.sql
20260408_011144_backfill_schema_migrations.sql
20260408_013542_drop_alembic_version.sql
20260408_120000_jarvis_alpha_writer_role.sql
20260408_130000_security_definer_functions.sql   ← Creates record_buddy_event (wrong types)
20260408_140000_record_buddy_event_fix.sql       ← Fixes record_buddy_event types
20260408_150000_evict_fix_and_promote_rip.sql
```

After deleting 008, removing it from this sequence produces **identical output**. The 005 → 011 → 20260408_140000 chain fully explains the live schema.

**Bottom line:** Deleting `008_buddy_events.sql` is safe. No migration, no script, and no application code depends on it. The runner already treats it as applied (ghost record). Deletion simplifies the migration chain with zero functional risk.
