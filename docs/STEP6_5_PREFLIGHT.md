# Step 6.5 Pre-Flight Discovery Report
**Date:** 2026-04-08  
**Scope:** TD-32, TD-33, TD-34, TD-37 — Foundation Hardening  
**Status:** READ-ONLY discovery — no migrations applied, no services restarted

---

## 1. Pipeline Health Check

### FINDINGS

**jarvisalpha_pull.sh** (scripts/jarvisalpha_pull.sh):

```
Lines 47–58:
if [ "$(hostname -s)" = "jarvis-brain" ]; then
  echo "Running database migrations..."
  if ! bash "${REPO_DIR}/scripts/apply_migrations.sh"; then
    echo "❌ MIGRATION FAILED — aborting pull deploy."
    exit 1
  fi
else
  echo "ℹ️  Skipping migrations — not on Brain (host: $(hostname -s))"
fi
```

Hostname guard: **PRESENT** (commit 2560c84). Migration runner wired via `bash "${REPO_DIR}/scripts/apply_migrations.sh"`: **PRESENT**. No Alembic references.

**restart_alpha.sh** (scripts/restart_alpha.sh):

```
Lines 59–65:
echo "Running database migrations..."
if ! bash ~/jarvis-alpha/scripts/apply_migrations.sh; then
  echo "❌ MIGRATION FAILED — aborting restart."
  exit 1
fi
```

Alembic: **NOT PRESENT** (confirmed ripped). apply_migrations.sh: **WIRED** (hard exit on failure before any services load).

**apply_migrations.sh** (scripts/apply_migrations.sh):
- Advisory lock prevents concurrent runs.
- Lexical file ordering over `brain/db/migrations/*.sql`.
- SHA-256 checksum gating: skips already-applied, aborts on mismatch.
- Hostname guard at line 33: `hostname -s` must equal `jarvis-brain`.

### INTERPRETATION
Both pull and restart paths are safe. Migrations will only run on Brain, fail-loud, and abort service load on error. No Alembic artifacts remain.

### RISK
- `apply_migrations.sh` uses `hostname -s` (same as pull.sh). Consistent — no divergence risk.
- One missing file in the migrations directory (`004_taskgraph_columns.sql` — see §4 bonus finding): runner ignores it (only iterates files that exist), but the schema state is not fully reproducible from the repo.

---

## 2. Token State (read-only)

All three nodes probed via SSH. JWT `exp` claims decoded from second Base64url segment.

### FINDINGS

**Brain** (`jarvisbrain@jarvis-brain.tail40ed36.ts.net`, secrets at `~/jarvis/.secrets`):

| Token Name | exp (unix) | Days Remaining |
|---|---|---|
| ALPHA_BUDDY_TOKEN | 1776254794 | **6.7** |

**Gateway** (`infranet@100.112.63.25`, secrets at `~/jarvis/.secrets`):

| Token Name | exp (unix) | Days Remaining |
|---|---|---|
| ALPHA_SERVICE_TOKEN | 1776257843 | **6.8** |

**Sandbox** (`jarvissand@100.124.172.14`, secrets at `~/.secrets`):

| Token Name | exp (unix) | Days Remaining |
|---|---|---|
| ALPHA_SERVICE_TOKEN | 1776255042 | **6.7** |

### INTERPRETATION
All tokens are healthy. No node is within the 2-day minimum threshold that triggers rotation. Step 6.5 can proceed without a rotation pre-run.

### RISK
Tokens expire in ~7 days. If Step 6.5 work spans multiple days and rotation guard fires during schema changes (e.g., RLS enabled but app broken), a failed health check during rotation could cascade. Low probability but worth noting.

---

## 3. Rotation Guard Health

Log path (from plist): `~/jarvis-alpha/logs/token_rotation.log`

### FINDINGS

**Brain** — raw tail (last entries):
```json
{"timestamp": "2026-04-08T12:56:04.799857+00:00", "level": "info", "service": "token_rotation", "node": "brain", "message": "rotation started"}
{"timestamp": "2026-04-08T12:56:04.800154+00:00", "level": "info", "service": "token_rotation", "node": "brain", "message": "rotation skipped \u2014 token still valid", "days_remaining": 6.97, "min_days_remaining": 2.0}
```

**Gateway** — raw tail (last entries):
```json
{"timestamp": "2026-04-08T12:57:23.856882+00:00", "level": "info", "service": "token_rotation", "node": "gateway", "message": "rotation started"}
{"timestamp": "2026-04-08T12:57:23.925491+00:00", "level": "info", "service": "token_rotation", "node": "gateway", "message": "token generated", "token_length": 660}
{"timestamp": "2026-04-08T12:57:23.927054+00:00", "level": "info", "service": "token_rotation", "node": "gateway", "message": "secrets file updated", "path": "/Users/infranet/jarvis/.secrets"}
{"timestamp": "2026-04-08T12:57:23.987836+00:00", "level": "info", "service": "token_rotation", "node": "gateway", "message": "verification result: ok (health 200)"}
{"timestamp": "2026-04-08T12:57:23.987936+00:00", "level": "info", "service": "token_rotation", "node": "gateway", "message": "rotation complete"}
{"timestamp": "2026-04-08T12:58:13.211434+00:00", "level": "info", "service": "token_rotation", "node": "gateway", "message": "rotation started"}
{"timestamp": "2026-04-08T12:58:13.211827+00:00", "level": "info", "service": "token_rotation", "node": "gateway", "message": "rotation skipped \u2014 token still valid", "days_remaining": 7.0, "min_days_remaining": 2.0}
```

**Sandbox** — raw tail (last entries):
```json
{"timestamp": "2026-04-08T12:59:07.656073+00:00", "level": "info", "service": "token_rotation", "node": "sandbox", "message": "rotation started"}
{"timestamp": "2026-04-08T12:59:07.657073+00:00", "level": "info", "service": "token_rotation", "node": "sandbox", "message": "rotation skipped \u2014 token still valid", "days_remaining": 6.97, "min_days_remaining": 2.0}
```

### INTERPRETATION
All three nodes show "rotation skipped — token still valid" as the most recent message, timestamped 2026-04-08 (today). Gateway shows a mid-session rotation that completed cleanly (health 200) followed immediately by a skip — this is the `RunAtLoad` firing twice at startup after LaunchAgent reload. Normal behavior. Guard is healthy on all nodes.

### RISK
None blocking. Guard is live and logging correctly on all three nodes.

---

## 4. Live Schema — alpha_buddy_events (TD-32)

### FINDINGS

**Raw psql `\d alpha_buddy_events` output (Brain, live):**
```
                        Table "public.alpha_buddy_events"
   Column   |           Type           | Collation | Nullable |      Default      
------------+--------------------------+-----------+----------+-------------------
 id         | uuid                     |           | not null | gen_random_uuid()
 user_id    | text                     |           |          | 
 event_type | text                     |           | not null | 
 title      | text                     |           | not null | 
 body       | text                     |           |          | 
 priority   | integer                  |           | not null | 2
 read       | boolean                  |           | not null | false
 created_at | timestamp with time zone |           | not null | now()
 source     | text                     |           |          | 
 payload    | jsonb                    |           |          | 
Indexes:
    "alpha_buddy_events_pkey" PRIMARY KEY, btree (id)
    "idx_buddy_events_unread" btree (read, created_at DESC) WHERE read = false
    "idx_buddy_events_user" btree (user_id, read, created_at DESC)
Check constraints:
    "alpha_buddy_events_event_type_check" CHECK (event_type = ANY (ARRAY['alert','reminder','suggestion','system']))
```

No "Row-level security: enabled" header. No "Policies:" section. **RLS is disabled. No policies exist.**

**Migrations touching alpha_buddy_events:**
- `005_buddy_events.sql` — creates table (original schema)
- `008_buddy_events.sql` — `CREATE TABLE IF NOT EXISTS` (conflict schema) + RLS + policy
- `011_buddy_events_columns.sql` — `ADD COLUMN source TEXT; ADD COLUMN payload JSONB`

**schema_migrations table state** (Brain):
| File | applied_at |
|---|---|
| 005_buddy_events.sql | NULL (backfilled) |
| 008_buddy_events.sql | NULL (backfilled) |
| 011_buddy_events_columns.sql | NULL (backfilled) |

All three are recorded but applied_at is NULL (registered by the 2026-04-07 backfill run, not applied by the runner). The migration runner will skip all three on next run.

**Side-by-side schema comparison:**

| Column | 005 schema | 008 schema | Live (psql) |
|---|---|---|---|
| id | UUID PK | UUID PK | UUID PK ✓ |
| user_id | TEXT | ❌ absent | TEXT ✓ (matches 005) |
| event_type | TEXT CHECK (alert/reminder/suggestion/system) | TEXT CHECK (graph_complete/graph_halted/step_failed/step_retrying/ci_required/approval_required) | TEXT CHECK (alert/reminder/suggestion/system) ✓ (matches 005) |
| title | TEXT NOT NULL | ❌ absent | TEXT NOT NULL ✓ (matches 005) |
| body | TEXT | ❌ absent | TEXT ✓ (matches 005) |
| priority | INT DEFAULT 2 | TEXT DEFAULT 'normal' (low/normal/high/critical) | INT DEFAULT 2 ✓ (matches 005) |
| read | BOOLEAN DEFAULT false | BOOLEAN DEFAULT false | BOOLEAN DEFAULT false ✓ |
| created_at | TIMESTAMPTZ | TIMESTAMPTZ | TIMESTAMPTZ ✓ |
| graph_id | ❌ absent | UUID FK → alpha_task_graphs | ❌ absent ✓ (FK never created) |
| step_id | ❌ absent | UUID FK → alpha_task_steps | ❌ absent ✓ |
| message | ❌ absent | TEXT NOT NULL | ❌ absent ✓ |
| source | ❌ absent | ❌ absent | TEXT (added by 011) |
| payload | ❌ absent | ❌ absent | JSONB (added by 011) |
| RLS | none | ENABLED | **DISABLED** |
| Policy | none | buddy_events_isolation (jarvis.current_user / jarvis.role) | **NONE** |

**Why 008 failed silently:** `008_buddy_events.sql` wraps everything in a single `BEGIN/COMMIT` transaction. `CREATE TABLE IF NOT EXISTS` silently succeeds (table already exists from 005). The subsequent `CREATE POLICY buddy_events_isolation ... USING (graph_id IN (...))` references column `graph_id` which does not exist in the live table. PostgreSQL raises an error, rolling back the entire transaction. Result: `ENABLE ROW LEVEL SECURITY` is also rolled back. The table retains the 005 shape with no RLS.

**Winner schema:** 005_buddy_events.sql + 011_buddy_events_columns.sql  
**Loser (to clean up):** 008_buddy_events.sql — its schema is incompatible, its transaction was dead-on-arrival, its entry in schema_migrations is a ghost record.

**Bonus finding — missing migration file:** `schema_migrations` records `004_taskgraph_columns.sql` as the most recently runner-applied migration (`applied_at = 2026-04-08 08:38:16`). This file does **not exist** in `brain/db/migrations/`. It was applied on Brain and then removed from the repo. The runner ignores missing files (iterates only what's in the directory), so it won't abort. But the schema state includes changes from a file that can't be reviewed or re-applied.

### INTERPRETATION
The live schema is unambiguously the 005 lineage. The 008 schema was abandoned by a transaction rollback. TD-32 fix is: delete `008_buddy_events.sql`, create a new migration (`016_buddy_events_rls.sql`) that adds RLS to the live 005-shape table with a policy using the canonical GUC convention (rls.* per TD-37 decision).

### RISK
- The ghost record for `008_buddy_events.sql` in schema_migrations means the migration runner will skip it permanently. The new Step 6.5 migration must use a new filename.
- The missing `004_taskgraph_columns.sql` file should be reconstructed or its absence documented before Step 6.5 — a future clean install would be missing those schema changes.

---

## 5. Live Schema — alpha_conversation_memory (TD-34)

### FINDINGS

**RLS / FORCE RLS state:**
```sql
SELECT relname, relrowsecurity, relforcerowsecurity 
FROM pg_class WHERE relname = 'alpha_conversation_memory';

          relname          | relrowsecurity | relforcerowsecurity 
---------------------------+----------------+---------------------
 alpha_conversation_memory | t              | f
```

- `relrowsecurity = t` → **RLS IS ENABLED**
- `relforcerowsecurity = f` → **FORCE RLS is NOT set** — table owner and superusers bypass RLS

**Active policies (from `\d` output):**
```
POLICY "alpha_memory_isolation"
  USING (((user_id = current_setting('jarvis.current_user', true)) 
          OR (current_setting('jarvis.role', true) = 'platform_admin')))
  
POLICY "child_memory_rating" FOR SELECT
  USING (((current_setting('app.profile_role', true) = 'admin') 
          OR (rating_level(content_rating) <= rating_level(current_setting('app.max_rating', true)))))

POLICY "child_memory_write" FOR INSERT
  WITH CHECK ((current_setting('app.profile_role', true) = 'admin'))
```

**GUC conventions in use on this table:**
| Policy | Convention | Columns checked |
|---|---|---|
| alpha_memory_isolation | `jarvis.*` | `jarvis.current_user`, `jarvis.role` |
| child_memory_rating | `app.*` | `app.profile_role`, `app.max_rating` |
| child_memory_write | `app.*` | `app.profile_role` |

Mixed conventions on a single table: `jarvis.*` (legacy) and `app.*` (newer). This is the TD-37 split on display.

**Full column list (from psql `\d`):**
```
id, workspace_id, user_id, session_id, role, content, embedding (vector(768)),
memory_type, persistent, created_at, tier, importance_score, last_accessed_at,
summary, access_count, content_rating
```

**Orphan policy risk if FORCE RLS were enabled today:**
`child_memory_write` has no USING clause (INSERT-only). If `app.profile_role` is not set by a writer (e.g., buddy_agent, executor), any INSERT would be blocked once FORCE RLS is in place. Currently, jarvisbrain (pool user) is the table owner and bypasses RLS — so buddy's DELETEs and memory.py's operations succeed even though they only set `jarvis.current_user` (not `app.profile_role`).

### INTERPRETATION
TD-34 appears to describe an historical state. RLS is now enabled (likely added during a prior migration), but **FORCE ROW LEVEL SECURITY is absent**. The practical effect: the jarvisbrain DB user (used by buddy_agent, executor, memory.py, watchdog) bypasses all policies. Routes use `rls_connection()` which sets role to `jarvis_alpha_app` and sets all GUC conventions, so routes enforce RLS correctly.

TD-34 fix requires two components:
1. `ALTER TABLE alpha_conversation_memory FORCE ROW LEVEL SECURITY` — closes the owner-bypass hole
2. SECURITY DEFINER functions for buddy/executor access to memory — so those internal writers can operate without needing GUC setup

### RISK
Adding FORCE RLS without SECURITY DEFINER in place first will break:
- buddy_agent.py DELETEs at lines 127–184 (no GUC set, would be blocked by alpha_memory_isolation)
- memory.py operations via MemoryService (sets `jarvis.current_user` but not `app.profile_role` — child_memory_write INSERT would block)
- executor.py at lines 46–47 (sets `jarvis.*` only — no `app.*`)

**FORCE RLS must NOT be applied until SECURITY DEFINER wrappers exist.**

---

## 6. GUC Convention Inventory (TD-37)

### FINDINGS

**All live policies with GUC convention tags** (from `pg_policy` full scan):

| Table | Policy | Convention | GUC variables used |
|---|---|---|---|
| alpha_conversation_memory | alpha_memory_isolation | `jarvis.*` | jarvis.current_user, jarvis.role |
| alpha_conversation_memory | child_memory_rating | `app.*` | app.profile_role, app.max_rating |
| alpha_conversation_memory | child_memory_write | `app.*` | app.profile_role |
| alpha_semantic_memory | semantic_isolation | `jarvis.*` | jarvis.current_user, jarvis.is_admin |
| alpha_task_graphs | task_graph_isolation | `jarvis.*` | jarvis.current_user, jarvis.role |
| alpha_task_graphs | child_task_isolation | `app.*` | app.profile_role |
| alpha_task_steps | task_step_isolation | `jarvis.*` | jarvis.current_user, jarvis.role |
| alpha_task_events | task_events_read | `jarvis.*` | jarvis.role, jarvis.current_user |
| chat_threads | chat_threads_isolation | `rls.*` | rls.user_id |
| chat_threads | child_thread_isolation | `app.*` | app.profile_role, app.profile_id |
| chat_messages | chat_messages_isolation | `rls.*` | rls.user_id |
| chat_messages | child_content_rating | `app.*` | app.profile_role, app.max_rating |
| chat_messages | child_message_isolation | `app.*` | app.profile_role, app.profile_id |
| vault_documents | vault_documents_read | `app.*` | app.profile_role |
| vault_documents | vault_documents_write | `app.*` | app.profile_role |
| vault_pipeline | vault_pipeline_admin | `app.*` | app.profile_role |
| vault_access_log | vault_access_log_admin | `app.*` | app.profile_role |
| alpha_watchdog_events | watchdog_events_system_write | `rls.*` | rls.user_id |
| alpha_watchdog_events | watchdog_events_read | (none) | — |

**Note on `jarvis.is_admin`:** `alpha_semantic_memory.semantic_isolation` uses `jarvis.is_admin` — a fourth GUC name not used anywhere else and not set by any writer (rls.py sets `jarvis.role`, not `jarvis.is_admin`). This is a latent bug: the admin bypass on semantic_isolation will never fire.

**Code inventory — set_config callers:**

| File | Line(s) | GUC convention | Context |
|---|---|---|---|
| brain/db/rls.py | 89, 92, 95, 98, 101 | `app.*` | rls_connection() — FastAPI route helper |
| brain/db/rls.py | 105, 108 | `jarvis.*` | rls_connection() — legacy compat layer |
| brain/db/rls.py | 112 | `rls.*` | rls_connection() — chat/watchdog compat |
| brain/tasks/executor.py | 46, 47 | `jarvis.*` | _bind_executor_rls() |
| brain/tasks/executor.py | 480, 481 | `jarvis.*` | inline bind in second call site |
| brain/tasks/watchdog.py | 29, 30 | `jarvis.*` | _bind_watchdog_rls() |
| brain/routes/dev.py | 54, 58 | `jarvis.*` | dev endpoint auth |
| brain/routes/dev.py | 272, 276 | `jarvis.*` | second dev endpoint call site |
| brain/routes/watchdog.py | 224 | `rls.*` | watchdog ingest (system writer) |
| brain/agents/watchdog_agent.py | 122 | `rls.*` | watchdog event write |
| brain/agents/buddy_agent.py | 189 | `jarvis.*` | one of four connection blocks (memory read only) |
| brain/memory/memory.py | 131, 160, 259, 295, 324 | `jarvis.*` | all memory read/write operations |

**Summary — writer GUC convention matrix:**

| Writer | `app.*` | `jarvis.*` | `rls.*` | Coverage |
|---|---|---|---|---|
| FastAPI routes (rls_connection) | ✅ | ✅ | ✅ | All three — complete |
| executor | ❌ | ✅ | ❌ | jarvis.* only |
| tasks/watchdog | ❌ | ✅ | ❌ | jarvis.* only |
| routes/dev | ❌ | ✅ | ❌ | jarvis.* only |
| routes/watchdog (system write) | ❌ | ❌ | ✅ | rls.* only |
| watchdog_agent (system write) | ❌ | ❌ | ✅ | rls.* only |
| buddy_agent | ❌ | partial (1/4 conn blocks) | ❌ | incomplete |
| memory.py | ❌ | ✅ | ❌ | jarvis.* only |

### INTERPRETATION
Three GUC namespaces are live: `jarvis.*` (legacy), `app.*` (newer, child-profile-aware), `rls.*` (chat + watchdog). The TD-37 decision is to canonicalize on `rls.*`. This is a large migration: 11 of 18 policies currently use `jarvis.*` or `app.*`.

`rls_connection()` already sets all three simultaneously — this is the "strangler" compatibility shim. The consolidation path is: rewrite policies to use `rls.*`, then remove the redundant `jarvis.*` and `app.*` set_config calls from rls_connection() and all background writers.

**Additional finding — `jarvis.is_admin` orphan:** The `semantic_isolation` policy uses `jarvis.is_admin` which is set by no writer. Admin bypass on `alpha_semantic_memory` is currently non-functional. Must be fixed in Step 6.5 (either rename to `jarvis.role` = 'platform_admin' pattern, or canonicalize to the rls.* convention).

### RISK
The strangler migration requires coordinated policy rewrites and writer updates. Doing them out of order will break either routes or background services. Recommended sequence: (1) add new `rls.*`-based policies alongside existing ones, (2) update all writers to set `rls.*`, (3) drop old policies.

---

## 7. Buddy Write Path Audit (TD-33)

### FINDINGS

**INSERT locations in alpha_buddy_events:**

1. **buddy_agent.py — `_write_event()` function** (lines 35–46)
   ```python
   await conn.execute(
       """INSERT INTO alpha_buddy_events
          (user_id, event_type, title, body, priority)
          VALUES ($1, $2, $3, $4, $5)""",
       user_id, event_type, title, body, priority,
   )
   ```
   **GUC set before this INSERT?** No. `_write_event()` is called from four connection blocks in `_run_cycle()`. None of those connection blocks set any GUC before calling `_write_event()`.

   The one GUC call in buddy_agent.py is at line 189:
   ```python
   await conn.execute("SELECT set_config('jarvis.current_user', $1, true)", str(user_id))
   ```
   This is in a **separate connection block** (lines 187–212) used for reading aging memories — **not** the same connection used for writes.

2. **approval_notifier.py — inline INSERT** (lines 146–154)
   ```python
   await conn.execute(
       """INSERT INTO alpha_buddy_events
          (event_type, title, body, priority, source, payload)
          VALUES ('alert', $1, $2, $3, 'approval_gateway', $4)""",
       ...
   )
   ```
   **GUC set before this INSERT?** No. Raw `pool.acquire()` with no set_config. Note: also omits `user_id` — approval events are inserted as NULL user_id.

**RLS policy cross-reference:**
Current state: `alpha_buddy_events` has **no RLS policy and RLS is disabled**. The `008_buddy_events.sql` policy (`buddy_events_isolation` using `jarvis.current_user`) never landed due to the transaction rollback (§4). There is currently no policy that would filter buddy writes.

**Current write behavior:**
All writes to `alpha_buddy_events` succeed unconditionally regardless of GUC state. The jarvisbrain DB user connects without `SET ROLE` and has superowner-level access. No writes are silently filtered today.

**Post-fix write behavior (what changes in Step 6.5):**
Once a new `alpha_buddy_events` RLS policy is created (required by TD-32 fix), buddy writes will break unless one of:
- A) SECURITY DEFINER INSERT function is used (decided: School A)
- B) `rls.user_id` is set before each write (fragile given 4 separate connection blocks)

**Schema compatibility check:**
Both current INSERT callers use the live 005-shaped schema (user_id/event_type/title/body/priority + source/payload). Neither uses the 008 schema (graph_id/message). Code matches live schema. ✅

### INTERPRETATION
"Buddy writes silently filtered" is **currently false** — RLS is disabled. The statement is forward-looking: once Step 6.5 enables RLS on `alpha_buddy_events`, buddy writes will be silently filtered (zero rows written, no error) unless SECURITY DEFINER wrappers are in place first.

Two writers need SECURITY DEFINER coverage:
1. `buddy_agent.py` — `_write_event()` function (4 call sites inside `_run_cycle()`)
2. `approval_notifier.py` — inline INSERT at line 147

### RISK
The approval_notifier INSERT omits `user_id`. If the new `alpha_buddy_events` policy enforces `user_id IS NOT NULL` or `user_id = current_setting(...)`, approval events will fail even with SECURITY DEFINER unless the policy explicitly allows NULL user_id (system events). The new policy must accommodate NULL user_id rows.

---

## OPEN QUESTIONS

1. **`004_taskgraph_columns.sql` missing from repo** — This migration was applied on Brain on 2026-04-08 08:38:16 but the file no longer exists in `brain/db/migrations/`. What columns does it add to `alpha_task_graphs`? Should the file be reconstructed and committed, or documented as intentionally removed?

2. **`jarvis.is_admin` orphan GUC** — `alpha_semantic_memory.semantic_isolation` uses `current_setting('jarvis.is_admin', true) = 'true'` but no writer sets this. The admin bypass path on semantic memory is permanently disabled. Is this intentional (admin doesn't need semantic memory access)? Or should the policy be updated as part of Step 6.5?

3. **New `alpha_buddy_events` RLS policy — event_type enum** — The 005 schema has `event_type IN ('alert','reminder','suggestion','system')`. The 008 schema had a task-graph-centric enum. For Step 6.5, what event_type values should the canonical schema support? Should the CHECK constraint be expanded for future task-graph events, or stay as-is?

4. **NULL user_id in alpha_buddy_events** — approval_notifier.py inserts with NULL user_id (system-level events). The new RLS policy must handle this. Should system events (user_id IS NULL) be world-readable, or should a `source = 'approval_gateway'` column narrow visibility?

5. **SECURITY DEFINER function ownership** — SECURITY DEFINER functions run as their definer, not the caller. Should the buddy/approval SECURITY DEFINER functions be owned by jarvisbrain (superuser) or a dedicated `jarvis_alpha_internal` role? The latter is cleaner but requires a new role.

6. **`alpha_buddy_events` 008 entry in schema_migrations** — The ghost record for `008_buddy_events.sql` has a checksum that will never match a future file of that name (since the file will be deleted). The runner will skip it. Should the record be manually deleted from `schema_migrations` to allow a new file named `008_buddy_events.sql` to apply, or should the new migration use a higher number (e.g., `016_buddy_events_rls.sql`)?

---

## GO / NO-GO

**Verdict: CONDITIONAL GO**

Step 6.5 can proceed with the following pre-conditions:

| Pre-condition | Status |
|---|---|
| Pipeline health (pull + restart) | ✅ READY |
| Token expiry (all nodes > 2 days) | ✅ READY (6.7–6.8 days) |
| Rotation guard active on all nodes | ✅ READY |
| Live schema understood (TD-32) | ✅ READY — 005 shape confirmed, 008 ghost identified |
| RLS state understood (TD-34) | ✅ READY — enabled but FORCE not set; risk path documented |
| GUC inventory complete (TD-37) | ✅ READY — all writers mapped |
| Buddy write path audited (TD-33) | ✅ READY — no current breakage; post-fix risk documented |

**Blocking items before writing migration code:**
1. **Decision needed on Q6** (open question #6): use new filename (`016_`) vs. clean up the `schema_migrations` ghost record for `008_buddy_events.sql`.
2. **Decision needed on Q4**: NULL user_id handling in the new alpha_buddy_events RLS policy.
3. **SECURITY DEFINER wrappers must be implemented before FORCE RLS on alpha_conversation_memory** — these can be the first migration in the step.

**Recommended execution order for Step 6.5:**
1. Create SECURITY DEFINER functions for buddy writes (alpha_buddy_events + alpha_conversation_memory access)
2. Fix alpha_buddy_events schema: drop 008 ghost record, create new policy on 005-shape table
3. Add FORCE ROW LEVEL SECURITY to alpha_conversation_memory
4. Begin strangler GUC consolidation: add rls.* aliases to all policies, verify all writers set rls.*
5. Drop legacy jarvis.* and app.* GUC calls from policies (after all writers updated)
