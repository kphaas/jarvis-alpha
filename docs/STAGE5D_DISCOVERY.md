# STAGE5D_DISCOVERY.md — Stage 5d Pre-Flight Discovery (Background Pool Cutover)

Phase 1 discovery for flipping the remaining 3 background asyncpg pools from
`jarvisbrain` (BYPASSRLS, table owner) to `jarvis_alpha_writer`
(NOBYPASSRLS, non-owner). Same pattern as Stage 5b (FastAPI) and Stage 5c
(buddy). **Read-only discovery — no code edits, no commits, no migrations.**

---

## Summary

| Item | Verdict |
|------|---------|
| Pools to flip | 3 — `watchdog_agent`, `tasks/executor`, `tasks/watchdog` |
| Distinct tables touched | 5 — `alpha_node_registry`, `alpha_watchdog_events`, `alpha_task_graphs`, `alpha_task_steps`, `alpha_task_events` |
| Tables already FORCE RLS | 0 |
| Tables with policies that BREAK under writer (admin GUC mismatch) | 2 — `alpha_task_graphs`, `alpha_task_steps` |
| Tables SAFE under writer with current code | 3 — `alpha_node_registry` (no RLS), `alpha_watchdog_events` (`rls.user_id='system'` already set), `alpha_task_events` (`current_user IS NOT NULL` clause) |
| New SECDEF wrappers minimally required | 0 if we fix the GUC; 4–6 if we go the SECDEF route |
| Env-var inconsistency | YES — `ALPHA_DB_DSN` (watchdog_agent) vs `JARVIS_ALPHA_DB_DSN` (executor + tasks/watchdog) |
| TD-49 status (2026-04-10) | SHIPPED — `priority→severity` rename confirmed in both executor.py and watchdog.py |
| NEW: `TaskGraphExecutor` status value bugs | 5 invalid status strings (`'complete'`, `'retrying'`, `'halted'`) violate CHECK constraints — pre-existing bug, file as TD |
| Dominant risk | Silent failure: executor sees 0 rows under writer due to GUC mismatch, appears healthy but stops processing |
| Recommended scope | Option B (GUC fix + per-service DSN, defer FORCE RLS to 5e) |

---

## 1. Pool Inventory

| # | Service | File:Line of `create_pool` | Env var read | How read | Min/Max | Currently authenticates as | Verified via |
|---|---------|---------------------------|--------------|----------|---------|---------------------------|--------------|
| 1 | service-health watchdog | `brain/agents/watchdog_agent.py:359` | `ALPHA_DB_DSN` | `os.environ[...]` (no fallback) | 1 / 3 | `jarvisbrain` | `pg_stat_activity` shows 2 idle `jarvisbrain` background backends; LaunchAgent `com.jarvis.alpha.watchdog.plist` runs `scripts/start_alpha_watchdog.sh` |
| 2 | task graph executor | `brain/tasks/executor.py:406` | `JARVIS_ALPHA_DB_DSN` | `get_secret(DB_DSN_KEY)` | 2 / 5 | `jarvisbrain` | LaunchAgent `com.jarvis.alpha.executor.plist` is loaded; same `jarvisbrain` backends in `pg_stat_activity` |
| 3 | task graph stuck-step watchdog | `brain/tasks/watchdog.py:149` | `JARVIS_ALPHA_DB_DSN` | `get_secret(DB_DSN_KEY)` | 1 / 2 | unknown — **no LaunchAgent for `tasks/watchdog.py` is present in `~/Library/LaunchAgents/`** | `ls ~/Library/LaunchAgents/` on brain shows no `com.jarvis.alpha.tasks_watchdog` plist; the file may be unrun |

`pg_stat_activity` snapshot at discovery time:

```
       usename       | application_name |         backend_start
---------------------+------------------+-------------------------------
 jarvisbrain         |                  | 2026-04-08 08:14:11.875478-04
 jarvisbrain         |                  | 2026-04-09 12:01:50.317205-04
 jarvis_alpha_writer |                  | 2026-04-09 17:25:03.745912-04
 jarvis_alpha_writer |                  | 2026-04-09 17:25:03.796671-04
 jarvis_alpha_writer |                  | 2026-04-09 17:25:08.478307-04
 jarvis_alpha_writer |                  | 2026-04-09 17:25:08.505947-04
 jarvisbrain         | psql             | 2026-04-09 17:28:06.067238-04
```

The 4 `jarvis_alpha_writer` backends are FastAPI (Stage 5b) + buddy (Stage 5c).
The 2 idle `jarvisbrain` backends are the only Stage-5d-target services
currently online — consistent with watchdog_agent + executor running, and
`tasks/watchdog.py` not running.

Pool min totals would be 4 if all 3 daemons were live; we observe 2. **This is
the strongest evidence that `brain/tasks/watchdog.py` is currently dead code
on the host.** See Open Question Q1.

---

## 2. Tables Touched (per service)

### 2.1 `brain/agents/watchdog_agent.py`

| File:Line | Op | Table | SQL shape |
|-----------|----|-------|-----------|
| `watchdog_agent.py:124` | INSERT | `alpha_watchdog_events` | bare `INSERT … VALUES …` (after `SET LOCAL rls.user_id='system'`) |
| `watchdog_agent.py:205` | SELECT | `alpha_node_registry` | bare `SELECT name, health_endpoint, node_type FROM alpha_node_registry WHERE …` |

Tables touched: `alpha_watchdog_events`, `alpha_node_registry`.

### 2.2 `brain/tasks/executor.py`

| File:Line | Op | Table | SQL shape |
|-----------|----|-------|-----------|
| `executor.py:101` | SELECT | `alpha_task_steps` | `find_ready_steps` self-join via `unnest(s.depends_on)` |
| `executor.py:185` | UPDATE | `alpha_task_graphs` | mark `running` |
| `executor.py:194` | SELECT | `alpha_task_graphs` | `SELECT status … WHERE id=$1` |
| `executor.py:206` | SELECT | `alpha_task_steps` | count remaining non-terminal |
| `executor.py:215` | UPDATE | `alpha_task_graphs` | mark `completed` |
| `executor.py:225` | SELECT | `alpha_task_steps` | count `awaiting approval` |
| `executor.py:235` | UPDATE | `alpha_task_graphs` | mark `needs_approval` |
| `executor.py:245` | SELECT | `alpha_task_steps` | count `failed` |
| `executor.py:253` | UPDATE | `alpha_task_graphs` | mark `failed` |
| `executor.py:281` | UPDATE | `alpha_task_steps` | mark `queued` (approval) |
| `executor.py:292` | UPDATE | `alpha_task_steps` | mark `running` |
| `executor.py:314` | UPDATE | `alpha_task_steps` | re-queue for approval |
| `executor.py:326` | UPDATE | `alpha_task_steps` | mark `completed` |
| `executor.py:344` | UPDATE | `alpha_task_steps` | retry — back to `pending` |
| `executor.py:364` | UPDATE | `alpha_task_steps` | mark `failed` (max retries) |
| `executor.py:377` | UPDATE | `alpha_task_steps` | cascade `skipped` to dependents |
| `executor.py:423` | SELECT | `alpha_task_graphs` | poll pending/running |
| `executor.py:433` | SELECT | `alpha_task_graphs` ⨝ `alpha_task_steps` | poll approved-and-resumable |
| `executor.py:495` | INSERT | `alpha_task_events` | `notify(...)` |
| `executor.py:514` | SELECT | `alpha_task_steps` | `resolve_ready_steps` (in-process API) |
| `executor.py:540` | UPDATE | `alpha_task_steps` | start running (in-process API) |
| `executor.py:549` | SELECT | `alpha_task_steps` | fetch step record |
| `executor.py:573` | SELECT | `alpha_task_steps` | `FOR UPDATE` |
| `executor.py:586` | UPDATE | `alpha_task_steps` | retry bookkeeping |
| `executor.py:597` | UPDATE | `alpha_task_steps` | reset to `pending` |
| `executor.py:607` | UPDATE | `alpha_task_steps` | mark `halted` |
| `executor.py:626` | UPDATE | `alpha_task_steps` | mark `complete` |
| `executor.py:643` | UPDATE | `alpha_task_graphs` | mark `running` |
| `executor.py:659` | SELECT | `alpha_task_steps` | gather statuses |
| `executor.py:675` | UPDATE | `alpha_task_graphs` | mark `complete` |
| `executor.py:686` | UPDATE | `alpha_task_graphs` | mark `halted` |
| `executor.py:708` | UPDATE | `alpha_task_graphs` | `recover_stuck_graphs` reset |

Tables touched: `alpha_task_graphs`, `alpha_task_steps`, `alpha_task_events`.

GUC binding: `_bind_executor_rls` / `_bind_worker_rls` set
`jarvis.current_user='admin'` and `jarvis.role='admin'`. **`'admin'` is NOT
the value the table policies expect — they expect `'platform_admin'`.** See §3.

### 2.3 `brain/tasks/watchdog.py`

| File:Line | Op | Table | SQL shape |
|-----------|----|-------|-----------|
| `watchdog.py:37` | SELECT | `alpha_task_steps` | find stuck (`status='running' AND age > timeout`) |
| `watchdog.py:55` | UPDATE | `alpha_task_steps` | reset to `pending` (retry) |
| `watchdog.py:74` | UPDATE | `alpha_task_steps` | mark `stuck` (max retries) |
| `watchdog.py:85` | UPDATE | `alpha_task_graphs` | mark graph `stuck` |
| `watchdog.py:109` | INSERT | `alpha_task_events` | event log |
| `watchdog.py:126` | SELECT | `alpha_task_graphs` ⨝ `alpha_task_steps` | find orphaned |
| `watchdog.py:140` | UPDATE | `alpha_task_graphs` | mark orphaned graph `failed` |

Tables touched: `alpha_task_steps`, `alpha_task_graphs`, `alpha_task_events`.
Same `_bind_watchdog_rls` setting `jarvis.current_user='admin'`,
`jarvis.role='admin'` — same mismatch as executor.

---

## 3. SECDEF Coverage Map

The Stage 3 + 5a + 5c SECDEF wrappers cover *memory* tables only
(`alpha_conversation_memory`, `alpha_semantic_memory`, `alpha_buddy_events`).
Searching `brain/db/migrations/` for `alpha_task_*`, `alpha_watchdog_events`,
or `alpha_node_registry` returns **zero matches** in any
`*security_definer*` migration. The only function that touches these tables
is `update_task_timestamp()` — a per-row `BEFORE UPDATE` trigger, not a
DML wrapper, owned by `jarvisbrain` and called automatically by the engine.

| Table | Existing SECDEF? | RLS | FORCE RLS | Bare DML under writer? | Verdict |
|-------|------------------|-----|-----------|------------------------|---------|
| `alpha_node_registry` | none | OFF | OFF | SELECT only | **SAFE** — no RLS at all, writer has SELECT grant |
| `alpha_watchdog_events` | none | ON | OFF | INSERT after `SET LOCAL rls.user_id='system'` | **SAFE** — INSERT WITH CHECK is satisfied; SELECT policy is `USING (true)` |
| `alpha_task_events` | none | ON | OFF | INSERT, SELECT under `jarvis.current_user='admin'` | **SAFE** — policy clause `current_setting('jarvis.current_user') IS NOT NULL` is satisfied; non-FORCE so writer is still subject to RLS but the predicate passes |
| `alpha_task_graphs` | none | ON | OFF | bare SELECT/UPDATE under `jarvis.role='admin'` | **BLOCKER** — `task_graph_isolation` checks for `jarvis.role='platform_admin'` (NOT `'admin'`); under writer the executor would see zero rows and silently no-op |
| `alpha_task_steps` | none | ON | OFF | bare SELECT/UPDATE | **BLOCKER** — `task_step_isolation` mirrors `task_graph_isolation`; same mismatch |

### Why `alpha_task_graphs` and `alpha_task_steps` break

Both policies look like:

```sql
USING (
  user_id = current_setting('jarvis.current_user', true)
  OR current_setting('jarvis.role', true) = 'platform_admin'
)
```

The executor calls:

```python
await conn.execute("SELECT set_config('jarvis.current_user', 'admin', true)")
await conn.execute("SELECT set_config('jarvis.role', 'admin', true)")
```

- `'admin' = user_id` → false (real user_ids are user identifiers like `'ken'`)
- `'admin' = 'platform_admin'` → false

Today, `jarvisbrain` has BYPASSRLS so the policy is skipped entirely. The
moment we flip the pool to `jarvis_alpha_writer` (NOBYPASSRLS, non-owner),
both policies kick in and **every executor query against task tables returns
0 rows or fails the WITH CHECK** (UPDATE matched-rows = 0). The executor
would appear healthy but stop making any progress. This is the dominant risk
of Stage 5d.

There is also a second policy on `alpha_task_graphs`:

```sql
POLICY child_task_isolation
  USING (current_setting('app.profile_role', true) = 'admin')
```

`app.profile_role` is never set by the executor either, so it does not save
us. Multiple permissive policies are OR'd; both must fail for access to be
denied; here both do.

---

## 4. Schema Snapshots

Connected as `jarvisbrain` on `jarvis-brain.tail40ed36.ts.net`. Raw `\d`
output, verbatim:

### 4.1 `\d alpha_task_graphs`

```
                             Table "public.alpha_task_graphs"
     Column      |           Type           | Collation | Nullable |       Default
-----------------+--------------------------+-----------+----------+----------------------
 id              | uuid                     |           | not null | gen_random_uuid()
 user_id         | text                     |           | not null |
 title           | text                     |           | not null |
 description     | text                     |           |          |
 graph_type      | text                     |           | not null | 'user_request'::text
 status          | text                     |           | not null | 'pending'::text
 priority        | integer                  |           | not null | 5
 user_type       | text                     |           | not null | 'adult'::text
 content_tier    | text                     |           | not null | 'unrestricted'::text
 metadata        | jsonb                    |           | not null | '{}'::jsonb
 checkpoint      | jsonb                    |           | not null | '{}'::jsonb
 max_retries     | integer                  |           | not null | 2
 timeout_seconds | integer                  |           | not null | 3600
 created_at      | timestamp with time zone |           | not null | now()
 updated_at      | timestamp with time zone |           | not null | now()
 started_at      | timestamp with time zone |           |          |
 completed_at    | timestamp with time zone |           |          |
 owner_profile   | text                     |           |          |
 source          | text                     |           | not null | 'manual'::text
 ci_required     | boolean                  |           | not null | false
 ci_passed       | boolean                  |           |          |
Indexes:
    "alpha_task_graphs_pkey" PRIMARY KEY, btree (id)
    "idx_tg_status" btree (status)
    "idx_tg_type" btree (graph_type)
    "idx_tg_user_status" btree (user_id, status)
Check constraints:
    "alpha_task_graphs_content_tier_check" CHECK (content_tier = ANY (ARRAY['unrestricted'::text, 'filtered'::text, 'child_safe'::text]))
    "alpha_task_graphs_graph_type_check" CHECK (graph_type = ANY (ARRAY['overnight'::text, 'user_request'::text, 'agent'::text, 'maintenance'::text]))
    "alpha_task_graphs_priority_check" CHECK (priority >= 1 AND priority <= 10)
    "alpha_task_graphs_source_check" CHECK (source = ANY (ARRAY['manual'::text, 'agent'::text]))
    "alpha_task_graphs_status_check" CHECK (status = ANY (ARRAY['pending'::text, 'running'::text, 'completed'::text, 'failed'::text, 'stuck'::text, 'needs_approval'::text, 'cancelled'::text]))
    "alpha_task_graphs_user_type_check" CHECK (user_type = ANY (ARRAY['adult'::text, 'child'::text]))
    "chk_child_content_tier" CHECK (user_type = 'adult'::text OR user_type = 'child'::text AND content_tier = 'child_safe'::text)
Foreign-key constraints:
    "alpha_task_graphs_owner_profile_fkey" FOREIGN KEY (owner_profile) REFERENCES alpha_profiles(id)
Referenced by:
    TABLE "alpha_task_events" CONSTRAINT "alpha_task_events_graph_id_fkey" FOREIGN KEY (graph_id) REFERENCES alpha_task_graphs(id) ON DELETE SET NULL
    TABLE "alpha_task_steps" CONSTRAINT "alpha_task_steps_graph_id_fkey" FOREIGN KEY (graph_id) REFERENCES alpha_task_graphs(id) ON DELETE CASCADE
Policies:
    POLICY "child_task_isolation"
      USING ((current_setting('app.profile_role'::text, true) = 'admin'::text))
    POLICY "task_graph_isolation"
      USING (((user_id = current_setting('jarvis.current_user'::text, true)) OR (current_setting('jarvis.role'::text, true) = 'platform_admin'::text)))
Triggers:
    trg_graphs_updated BEFORE UPDATE ON alpha_task_graphs FOR EACH ROW EXECUTE FUNCTION update_task_timestamp()
```

### 4.2 `\d alpha_task_steps`

```
                              Table "public.alpha_task_steps"
      Column       |           Type           | Collation | Nullable |       Default
-------------------+--------------------------+-----------+----------+----------------------
 id                | uuid                     |           | not null | gen_random_uuid()
 graph_id          | uuid                     |           | not null |
 user_id           | text                     |           | not null |
 step_name         | text                     |           | not null |
 step_type         | text                     |           | not null |
 step_order        | integer                  |           | not null | 0
 status            | text                     |           | not null | 'pending'::text
 depends_on        | uuid[]                   |           | not null | '{}'::uuid[]
 content_tier      | text                     |           | not null | 'unrestricted'::text
 input             | jsonb                    |           | not null | '{}'::jsonb
 output            | jsonb                    |           | not null | '{}'::jsonb
 checkpoint        | jsonb                    |           | not null | '{}'::jsonb
 approval_required | boolean                  |           | not null | false
 approval_status   | text                     |           |          |
 approved_by       | text                     |           |          |
 approved_at       | timestamp with time zone |           |          |
 retry_count       | integer                  |           | not null | 0
 max_retries       | integer                  |           | not null | 2
 timeout_seconds   | integer                  |           | not null | 300
 error_message     | text                     |           |          |
 created_at        | timestamp with time zone |           | not null | now()
 updated_at        | timestamp with time zone |           | not null | now()
 started_at        | timestamp with time zone |           |          |
 completed_at      | timestamp with time zone |           |          |
 label             | text                     |           |          |
 executor          | text                     |           |          |
 tool              | text                     |           |          |
Indexes:
    "alpha_task_steps_pkey" PRIMARY KEY, btree (id)
    "idx_ts_graph" btree (graph_id)
    "idx_ts_graph_order" btree (graph_id, step_order)
    "idx_ts_status" btree (status)
Check constraints:
    "alpha_task_steps_approval_status_check" CHECK (approval_status = ANY (ARRAY['pending'::text, 'approved'::text, 'denied'::text]))
    "alpha_task_steps_content_tier_check" CHECK (content_tier = ANY (ARRAY['unrestricted'::text, 'filtered'::text, 'child_safe'::text]))
    "alpha_task_steps_status_check" CHECK (status = ANY (ARRAY['pending'::text, 'queued'::text, 'running'::text, 'completed'::text, 'failed'::text, 'stuck'::text, 'skipped'::text, 'cancelled'::text]))
    "alpha_task_steps_step_type_check" CHECK (step_type = ANY (ARRAY['llm'::text, 'code'::text, 'tool'::text, 'approval'::text, 'condition'::text, 'parallel_gate'::text]))
Foreign-key constraints:
    "alpha_task_steps_graph_id_fkey" FOREIGN KEY (graph_id) REFERENCES alpha_task_graphs(id) ON DELETE CASCADE
Referenced by:
    TABLE "alpha_task_events" CONSTRAINT "alpha_task_events_step_id_fkey" FOREIGN KEY (step_id) REFERENCES alpha_task_steps(id) ON DELETE SET NULL
Policies:
    POLICY "task_step_isolation"
      USING (((user_id = current_setting('jarvis.current_user'::text, true)) OR (current_setting('jarvis.role'::text, true) = 'platform_admin'::text)))
Triggers:
    trg_enforce_child_step_tier BEFORE INSERT OR UPDATE ON alpha_task_steps FOR EACH ROW EXECUTE FUNCTION enforce_child_step_tier()
    trg_steps_updated BEFORE UPDATE ON alpha_task_steps FOR EACH ROW EXECUTE FUNCTION update_task_timestamp()
```

### 4.3 `\d alpha_task_events`

```
                         Table "public.alpha_task_events"
   Column   |           Type           | Collation | Nullable |      Default
------------+--------------------------+-----------+----------+-------------------
 id         | uuid                     |           | not null | gen_random_uuid()
 event_type | text                     |           | not null |
 graph_id   | uuid                     |           |          |
 step_id    | uuid                     |           |          |
 message    | text                     |           | not null | ''::text
 severity   | text                     |           | not null | 'normal'::text
 title      | text                     |           |          |
 detail     | jsonb                    |           |          | '{}'::jsonb
 source     | text                     |           |          | 'system'::text
 read       | boolean                  |           | not null | false
 created_at | timestamp with time zone |           | not null | now()
Indexes:
    "alpha_task_events_pkey" PRIMARY KEY, btree (id)
    "idx_task_events_graph" btree (graph_id)
    "idx_task_events_unread" btree (read, created_at)
Check constraints:
    "alpha_task_events_severity_check" CHECK (severity = ANY (ARRAY['low'::text, 'normal'::text, 'warning'::text, 'critical'::text]))
Foreign-key constraints:
    "alpha_task_events_graph_id_fkey" FOREIGN KEY (graph_id) REFERENCES alpha_task_graphs(id) ON DELETE SET NULL
    "alpha_task_events_step_id_fkey" FOREIGN KEY (step_id) REFERENCES alpha_task_steps(id) ON DELETE SET NULL
Policies:
    POLICY "task_events_read"
      USING (((current_setting('jarvis.role'::text, true) = 'platform_admin'::text) OR (current_setting('jarvis.current_user'::text, true) IS NOT NULL)))
```

Note: live schema does NOT match `008b_task_events.sql` (which declares
columns `priority`, `read`, no `severity`/`title`/`detail`/`source`). The
live schema has been migrated forward by some path that is not in the
checked-in migration set. **UPDATE (2026-04-10):** TD-49 shipped this
morning and renamed `priority` → `severity` in both `executor.py:497` and
`watchdog.py:111`. The live code now matches the live schema. Q3 below is
**partially resolved** — the forward migration path is still undocumented
but the column mismatch is no longer a blocker.

### 4.4 `\d alpha_watchdog_events`

```
                            Table "public.alpha_watchdog_events"
        Column        |           Type           | Collation | Nullable |      Default
----------------------+--------------------------+-----------+----------+-------------------
 id                   | uuid                     |           | not null | gen_random_uuid()
 service_name         | text                     |           | not null |
 node                 | text                     |           | not null |
 event_type           | text                     |           | not null |
 previous_state       | text                     |           |          |
 current_state        | text                     |           |          |
 consecutive_failures | integer                  |           |          | 0
 latency_ms           | numeric(10,2)            |           |          |
 http_status          | integer                  |           |          |
 error_message        | text                     |           |          |
 action_taken         | text                     |           |          |
 trace_id             | uuid                     |           |          |
 created_at           | timestamp with time zone |           |          | now()
Indexes:
    "alpha_watchdog_events_pkey" PRIMARY KEY, btree (id)
    "idx_watchdog_events_node" btree (node, created_at DESC)
    "idx_watchdog_events_service_time" btree (service_name, created_at DESC)
    "idx_watchdog_events_type_time" btree (event_type, created_at DESC)
Check constraints:
    "watchdog_event_type_check" CHECK (event_type = ANY (ARRAY['down'::text, 'restored'::text, 'degraded'::text, 'restart_triggered'::text, 'restart_succeeded'::text, 'restart_failed'::text, 'check_error'::text]))
Policies:
    POLICY "watchdog_events_read" FOR SELECT
      USING (true)
    POLICY "watchdog_events_system_write" FOR INSERT
      WITH CHECK ((current_setting('rls.user_id'::text, true) = 'system'::text))
```

### 4.5 `\d alpha_node_registry`

```
                                         Table "public.alpha_node_registry"
     Column      |           Type           | Collation | Nullable |                     Default
-----------------+--------------------------+-----------+----------+-------------------------------------------------
 id              | integer                  |           | not null | nextval('alpha_node_registry_id_seq'::regclass)
 name            | text                     |           | not null |
 display_name    | text                     |           | not null |
 role            | text                     |           | not null |
 node_type       | text                     |           | not null |
 tailscale_ip    | text                     |           |          |
 health_endpoint | text                     |           |          |
 cert_issued_at  | timestamp with time zone |           |          |
 cert_expires_at | timestamp with time zone |           |          |
 is_active       | boolean                  |           | not null | true
 created_at      | timestamp with time zone |           | not null | now()
Indexes:
    "alpha_node_registry_pkey" PRIMARY KEY, btree (id)
    "alpha_node_registry_name_key" UNIQUE CONSTRAINT, btree (name)
    "idx_node_registry_active" btree (is_active)
    "idx_node_registry_name" btree (name)
Check constraints:
    "alpha_node_registry_node_type_check" CHECK (node_type = ANY (ARRAY['service'::text, 'storage'::text, 'dev'::text, 'network'::text, 'mobile'::text]))
```

(No Policies section — RLS is OFF.)

---

## 5. RLS State for Each Table

Single query, executed as `jarvisbrain`:

```sql
SELECT c.relname,
       c.relrowsecurity   AS rls_enabled,
       c.relforcerowsecurity AS force_rls
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname='public'
  AND c.relname IN ('alpha_task_graphs','alpha_task_steps','alpha_task_events',
                    'alpha_watchdog_events','alpha_node_registry')
ORDER BY c.relname;
```

```
        relname        | rls_enabled | force_rls
-----------------------+-------------+-----------
 alpha_node_registry   | f           | f
 alpha_task_events     | t           | f
 alpha_task_graphs     | t           | f
 alpha_task_steps      | t           | f
 alpha_watchdog_events | t           | f
(5 rows)
```

GRANTs (executed via `information_schema.table_privileges`): all five tables
have full DML (`SELECT/INSERT/UPDATE/DELETE`) granted to both
`jarvis_alpha_app` and `jarvis_alpha_writer`. No GRANT work needed for 5d.
Role membership confirmed: `jarvis_alpha_writer` is a member of
`jarvis_alpha_app` (per Stage 5b hotfix migration `20260409_120000_*`).

**Bottom line:** none of the five tables is FORCE RLS yet; the BLOCKERs in §3
are pure GUC mismatches, not FORCE-RLS bypasses. Fixing the GUC value
unblocks the cutover without any new SECDEF wrappers.

---

## 6. Env Var Inconsistency

Current state:

| Service | Env var | Loaded by |
|---------|---------|-----------|
| `brain/agents/watchdog_agent.py` | `ALPHA_DB_DSN` | `os.environ[...]` direct |
| `brain/tasks/executor.py` | `JARVIS_ALPHA_DB_DSN` | `get_secret("JARVIS_ALPHA_DB_DSN")` |
| `brain/tasks/watchdog.py` | `JARVIS_ALPHA_DB_DSN` | `get_secret("JARVIS_ALPHA_DB_DSN")` |

For comparison, Stage 5b/5c established this pattern in `brain/core/config.py`:

```python
ALPHA_DB_DSN: str         = os.environ["ALPHA_DB_DSN"]          # legacy (still defined)
ALPHA_DB_DSN_WRITER: str  = os.environ["ALPHA_DB_DSN_WRITER"]   # FastAPI (5b)
ALPHA_DB_DSN_BUDDY: str   = os.environ["ALPHA_DB_DSN_BUDDY"]    # buddy   (5c)
```

`ALPHA_DB_DSN` is declared but no longer consumed by FastAPI; the only
in-tree consumer is `brain/agents/watchdog_agent.py`. `JARVIS_ALPHA_DB_DSN`
is a *different* secret entirely — it lives in `~/jarvis/.secrets` and is
loaded only by the `tasks/*` files via `get_secret()`. Two prefixes for the
same logical thing is the inconsistency.

### Options

a. **Per-service `ALPHA_DB_DSN_<SERVICE>` (matches 5b/5c)**
   - `ALPHA_DB_DSN_WATCHDOG`
   - `ALPHA_DB_DSN_EXECUTOR`
   - `ALPHA_DB_DSN_TASKS_WATCHDOG`
   - All loaded via `brain/core/config.py` (`os.environ[...]`, fail-fast).
   - Retire `ALPHA_DB_DSN` (legacy) and `JARVIS_ALPHA_DB_DSN` (`get_secret`)
     after the cutover ships and is observed clean.

b. Standardize to `JARVIS_ALPHA_DB_DSN_<SERVICE>` — breaks 5b/5c convention.

c. Single shared `ALPHA_DB_DSN_BACKGROUND` for all three — loses
   independent rollback per service.

**Recommendation: Option (a).** It is the only choice consistent with the
already-shipped 5b and 5c patterns; it preserves per-service rollback
(critical because `tasks/executor.py` and `watchdog_agent.py` have very
different blast radii); and it removes the `get_secret()` divergence so all
three services configure their pool through `brain/core/config.py` like
buddy and FastAPI.

---

## 7. Risk Surface

1. **Naked writes/reads needing wrapping (or fixing):**
   - Total DML sites across the 3 services: **~38** (see §2 tables).
   - Sites that touch tables with BLOCKER policies (`alpha_task_graphs` /
     `alpha_task_steps`): **~33** of those 38.
   - Sites that touch SAFE tables only (`alpha_node_registry`,
     `alpha_watchdog_events`, `alpha_task_events`): **~5** — these need no
     change.

2. **New SECDEF functions needed (Option B path — GUC fix):** **0**.
   - The GUC fix is a one-line change in three files (`'admin'` →
     `'platform_admin'`). No migration needed.
   - Alternative SECDEF path (Option C below) would need ~6 wrappers:
     `find_ready_steps`, `update_graph_status`, `update_step_status`,
     `count_steps_by_status`, `recover_stuck_graphs`, `find_orphaned_graphs`.
     Significant additional surface for no immediate safety gain because
     FORCE RLS is not yet enabled on these tables.

3. **Tables that should ALSO move to FORCE RLS as part of 5d:**
   - **None.** Stage 5d should be scoped to the role flip + GUC fix only.
   - FORCE RLS for `alpha_task_*` is a separate decision because it
     requires every admin/operator query path (FastAPI `/tasks` route,
     CLI tooling, ad-hoc psql sessions) to also satisfy the policy. That
     review is bigger than 5d.
   - Defer to Stage 5e (proposed): "FORCE RLS on task tables" as its own PR.

4. **GUC dependencies that would break under writer:**
   - `jarvis.current_user='admin'` and `jarvis.role='admin'` set by
     `_bind_executor_rls`/`_bind_worker_rls`/`_bind_watchdog_rls` —
     **the value `'admin'` is wrong**; the policies expect
     `'platform_admin'`. This is the only GUC dependency across the 3 files.
   - `rls.user_id='system'` set in `watchdog_agent.py:122` — already
     correct, no change needed.
   - No `app.profile_role` set anywhere in the 3 files — the
     `child_task_isolation` policy is unsatisfied today and stays
     unsatisfied; it's a parallel admin override path, not load-bearing.

5. **~~Schema drift on `alpha_task_events`~~ — RESOLVED by TD-49
   (2026-04-10).** Both `executor.py:497` and `watchdog.py:111` now write
   `severity` (matching the live column). Structured JSON error logging is
   in place on both `except` branches. No further action needed for 5d.

6. **NEW finding (2026-04-10): `TaskGraphExecutor` in-process API uses
   invalid status values.** The in-process `TaskGraphExecutor` class
   (`executor.py:473–728`) uses status strings that violate the CHECK
   constraints on `alpha_task_steps` and `alpha_task_graphs`:

   | File:Line | Status used | Table | Constraint allows |
   |-----------|-------------|-------|-------------------|
   | `executor.py:600` | `'retrying'` | `alpha_task_steps` | NO — not in `alpha_task_steps_status_check` |
   | `executor.py:619` | `'halted'` | `alpha_task_steps` | NO — not in `alpha_task_steps_status_check` |
   | `executor.py:639` | `'complete'` | `alpha_task_steps` | NO — should be `'completed'` |
   | `executor.py:681` | `'complete'` | `alpha_task_steps` | NO — used in status comparison, not DML, but indicates a design inconsistency |
   | `executor.py:690` | `'halted'` | `alpha_task_graphs` | NO — not in `alpha_task_graphs_status_check` |
   | `executor.py:704` | `'halted'` | `alpha_task_graphs` | NO — not in `alpha_task_graphs_status_check` |

   **Impact:** Any code path through the `TaskGraphExecutor` class that
   attempts to write `'retrying'`, `'halted'`, or `'complete'` will raise a
   CHECK constraint violation. This is a **pre-existing bug** unrelated to
   the role flip — it exists under `jarvisbrain` too. However, since the
   in-process API runs through FastAPI's pool (already on
   `jarvis_alpha_writer`), these paths may already be broken in production.
   **File as a separate TD before or during Stage 5d.** The standalone
   `main()` executor (lines 1–465) uses correct status values and is NOT
   affected.

---

## 8. Open Questions for Ken

**Q1. Is `brain/tasks/watchdog.py` actually running anywhere?**
No `com.jarvis.alpha.tasks_watchdog.plist` LaunchAgent on Brain. The 2 idle
`jarvisbrain` background connections in `pg_stat_activity` are consistent
with `watchdog_agent.py` + `executor.py` only. If `tasks/watchdog.py` is
dead code, the cleanest 5d move is to **delete the file** rather than fix
its DSN. Confirm intent.

**Q2. Should the executor use `'platform_admin'` or get its own
`'task_executor'` role?** The trivial GUC fix is changing
`'admin'` → `'platform_admin'` in three lines. The slightly less trivial
fix is introducing a new policy clause:
`OR current_setting('jarvis.role', true) = 'task_executor'`
…and having the executor set that. The benefit is least-privilege
auditability (a pg_stat trace can tell `task_executor` connections from
human admin sessions); the cost is one extra migration. Pick one.

**Q3. `alpha_task_events` schema drift.** The checked-in `008b_task_events.sql`
declares `priority TEXT`, `read BOOLEAN`. The live table has
`severity TEXT`, `read BOOLEAN`, `title`, `detail JSONB`, `source TEXT`,
and **no `priority` column at all**. **UPDATE (2026-04-10):** TD-49 shipped
today and fixed both `executor.py:497` and `watchdog.py:111` to write
`severity` instead of `priority`. The column mismatch is resolved. The
question of where the forward migration lives (it's not in the checked-in
migration set) remains open but is no longer a blocker for Stage 5d.

**Q4. `JARVIS_ALPHA_DB_DSN` vs `ALPHA_DB_DSN`.** Is there a historical
reason `tasks/executor.py` and `tasks/watchdog.py` use `get_secret()` from
`~/jarvis/.secrets` while `watchdog_agent.py` uses `os.environ[]` from the
LaunchAgent plist? If not, the cleanest 5d move standardizes both to plist
env vars routed through `brain/core/config.py`.

**Q5. Stage 5e vs 5d scope creep.** Should we pre-commit to a Stage 5e for
"FORCE RLS on task tables" so the 5d PR description can explicitly reference
it? Or leave it open until the 5d cutover is observed clean?

---

## 9. Recommended Stage 5d Scope

### Option A — Minimal (lowest blast radius)

- Flip `watchdog_agent.py` only to `jarvis_alpha_writer` via
  `ALPHA_DB_DSN_WATCHDOG`.
- Defer executor + tasks/watchdog flips to Stage 5d.2.
- **Effort:** 1 file edit, 1 secret line, 1 LaunchAgent restart.
- **Blast radius:** very small — `alpha_watchdog_events` is SAFE under writer
  (rls.user_id='system' already set), and `alpha_node_registry` has no RLS.
- **Why pick it:** if we want a Stage 5b/5c-style incremental cadence and
  zero risk to the executor.
- **Why NOT:** leaves the executor — by far the heaviest writer — unflipped,
  and forces a Stage 5d.2 with the harder discovery work anyway.

### Option B — GUC fix + per-service DSN, all three services (RECOMMENDED)

- Add `ALPHA_DB_DSN_WATCHDOG`, `ALPHA_DB_DSN_EXECUTOR`,
  `ALPHA_DB_DSN_TASKS_WATCHDOG` to `brain/core/config.py` and to
  `~/jarvis/.secrets` (Ken's manual step, mirrors 5c).
- Replace `'admin'` with `'platform_admin'` in `_bind_executor_rls`,
  `_bind_worker_rls` (`executor.py`), and `_bind_watchdog_rls`
  (`tasks/watchdog.py`). Three identical 1-line edits.
- Switch the three `create_pool` calls to read from the new DSN constants.
- Smoke-test against the live DB as `jarvis_alpha_writer` BEFORE the
  LaunchAgent flips:
  - `find_ready_steps` returns ≥1 row when `jarvis.role='platform_admin'`.
  - `executor.notify(...)` succeeds (also catches the §7.5 schema drift).
  - `watchdog_agent.py` cycle inserts a `check_error` row under writer.
- **Resolve Q1 first:** if `tasks/watchdog.py` is dead code, drop it from
  scope and delete the file instead.
- **Effort:** ~3 file edits + 3 secret lines + 1 migration of zero rows
  (no SQL needed) + 1 smoke script + 2 LaunchAgent restarts.
- **Blast radius:** medium. Fully reversible by reverting the DSN values
  in `~/jarvis/.secrets` and `launchctl kickstart -k`. The `'admin'` →
  `'platform_admin'` source-code change is also revert-safe (`jarvisbrain`
  has BYPASSRLS so the change is a no-op under the old DSN).
- **Why pick it:** finishes the background-pool cutover in one PR,
  matches the Stage 5b/5c shape, and defers FORCE RLS to its own
  considered review.

### Option C — Option B + SECDEF wrappers for every task-table DML site

- Wrap all ~33 task-table DML sites in `SECURITY DEFINER` functions
  (mirrors Stage 5a/5c approach for memory tables).
- Then flip the pools.
- **Effort:** large. ~6 new SECDEF functions (per §7.2), one new
  migration with ~150 lines, ~33 call-site rewrites in `executor.py` and
  `tasks/watchdog.py`, smoke tests for each wrapper.
- **Blast radius:** larger code surface in the same PR; higher review cost.
- **Why pick it:** only justified if Stage 5d ALSO enables FORCE RLS on
  task tables (otherwise the wrappers buy nothing the GUC fix doesn't).
- **Why NOT now:** FORCE RLS on task tables needs its own discovery
  (FastAPI `/tasks` route, CLI tools, ops tooling) — that work is bigger
  than 5d.

### Recommendation: **Option B**

Option B is the smallest change that gets all three pools off `jarvisbrain`
in one PR while preserving the 5b/5c rollback shape. Option C should be
queued behind a future Stage 5e ("FORCE RLS on task tables") that does the
SECDEF wrap and the FORCE flip together. Option A is acceptable if Ken
wants a more conservative cadence, but we will end up doing Option B's
discovery work for the 5d.2 PR anyway.

**Phase 2 should not start until Ken picks A/B/C and answers Q1–Q5.**

---

## 10. LaunchAgent Inventory (Task 6)

### 10.1 `com.jarvis.alpha.watchdog` (watchdog_agent.py)

- **Plist path (installed):** `~/Library/LaunchAgents/com.jarvis.alpha.watchdog.plist` (Brain)
- **Plist path (repo):** `~/jarvis-alpha/launchagents/com.jarvis.alpha.watchdog.plist`
- **Label:** `com.jarvis.alpha.watchdog`
- **ProgramArguments:** `/bin/bash /Users/jarvisbrain/jarvis-alpha/scripts/start_alpha_watchdog.sh`
- **WorkingDirectory:** `/Users/jarvisbrain/jarvis-alpha`
- **KeepAlive:** `SuccessfulExit=false, Crashed=true`
- **ThrottleInterval:** 30s
- **StandardOutPath:** `~/jarvis-alpha/logs/alpha_watchdog.log`
- **StandardErrorPath:** `~/jarvis-alpha/logs/alpha_watchdog_error.log`
- **EnvironmentVariables in plist:**
  - `JARVIS_NODE=brain`
  - `WATCHDOG_INTERVAL_SECONDS=60`
  - `WATCHDOG_FAILURE_THRESHOLD=3`
  - `WATCHDOG_CHECK_TIMEOUT_SECONDS=5`
- **DSN env vars in plist:** NONE — `ALPHA_DB_DSN` comes from `~/jarvis/.secrets` via `start_alpha_watchdog.sh` (`set -a; source ~/jarvis/.secrets; set +a`)
- **Start script:** `scripts/start_alpha_watchdog.sh` sources `~/jarvis/.secrets`, sets `PYTHONPATH`, execs `python3.12 -m brain.agents.watchdog_agent`

### 10.2 `com.jarvis.alpha.executor` (tasks/executor.py)

- **Plist path (installed):** `~/Library/LaunchAgents/com.jarvis.alpha.executor.plist` (Brain)
- **Plist path (repo):** `~/jarvis-alpha/launchagents/com.jarvis.alpha.executor.plist`
- **Label:** `com.jarvis.alpha.executor`
- **ProgramArguments:** `/bin/bash /Users/jarvisbrain/jarvis-alpha/scripts/start_alpha_executor.sh`
- **WorkingDirectory:** `/Users/jarvisbrain/jarvis-alpha`
- **KeepAlive:** `SuccessfulExit=false, Crashed=true`
- **ThrottleInterval:** 30s
- **StandardOutPath:** `~/jarvis-alpha/logs/alpha_executor.log`
- **StandardErrorPath:** `~/jarvis-alpha/logs/alpha_executor_error.log`
- **EnvironmentVariables in plist:** NONE
- **DSN env vars in plist:** NONE — `JARVIS_ALPHA_DB_DSN` comes from `~/jarvis/.secrets` via `start_alpha_executor.sh` and `get_secret()`
- **Start script:** `scripts/start_alpha_executor.sh` sources `~/jarvis/.secrets`, sets `PYTHONPATH`, execs `python3.12 -m brain.tasks.executor`

### 10.3 `tasks/watchdog.py` — NO LaunchAgent

- **No plist found** in `~/Library/LaunchAgents/` or anywhere in the repo tree.
- `tasks/watchdog.py` defines a `main()` with its own `asyncio.run()` and signal handlers, clearly intended to run as a standalone daemon.
- **But it has no launch mechanism.** No plist, no systemd unit, no cron entry.
- `pg_stat_activity` shows only 2 idle `jarvisbrain` backends (matching watchdog_agent + executor). If `tasks/watchdog.py` were running, we'd see a 3rd.
- **Conclusion:** `tasks/watchdog.py` is dead code on the host. See Q1.

---

## 11. GUC and `current_user` Dependencies (Task 5)

Full file:line audit of every GUC-related reference in the 3 target files.

### 11.1 `brain/agents/watchdog_agent.py`

| File:Line | Code | What it does |
|-----------|------|--------------|
| `watchdog_agent.py:27` | `os.environ.get("WATCHDOG_INTERVAL_SECONDS", "60")` | Non-DB env var — loop interval |
| `watchdog_agent.py:28` | `os.environ.get("WATCHDOG_FAILURE_THRESHOLD", "3")` | Non-DB env var — threshold |
| `watchdog_agent.py:29` | `os.environ.get("WATCHDOG_CHECK_TIMEOUT_SECONDS", "5")` | Non-DB env var — HTTP timeout |
| `watchdog_agent.py:30` | `os.environ.get("JARVIS_NODE", ...)` | Non-DB env var — node identity |
| `watchdog_agent.py:122` | `set_config('rls.user_id', 'system', true)` | Sets RLS GUC for `alpha_watchdog_events` INSERT — **CORRECT**, matches `watchdog_events_system_write` WITH CHECK |
| `watchdog_agent.py:358` | `os.environ["ALPHA_DB_DSN"]` | **DB DSN — direct `os.environ` access** (anti-pattern: should go through `brain/core/config.py`) |

**No reference to:** `jarvis.current_user`, `jarvis.role`, `app.profile_role`,
`_bind_worker_rls`, `set_rls_context`, `current_setting()`.
This file only touches `alpha_watchdog_events` (which uses `rls.user_id`)
and `alpha_node_registry` (no RLS). It does NOT touch task tables, so the
`jarvis.role='platform_admin'` mismatch is irrelevant here.

### 11.2 `brain/tasks/executor.py`

| File:Line | Code | What it does |
|-----------|------|--------------|
| `executor.py:46` | `set_config('jarvis.current_user', 'admin', true)` | `_bind_executor_rls` — **WRONG VALUE** (should be `'platform_admin'` or a real user_id) |
| `executor.py:47` | `set_config('jarvis.role', 'admin', true)` | `_bind_executor_rls` — **WRONG VALUE** (policies check for `'platform_admin'`) |
| `executor.py:480` | `set_config('jarvis.current_user', 'admin', true)` | `TaskGraphExecutor._bind_worker_rls` — **WRONG VALUE** (same) |
| `executor.py:481` | `set_config('jarvis.role', 'admin', true)` | `TaskGraphExecutor._bind_worker_rls` — **WRONG VALUE** (same) |

**Callers of `_bind_executor_rls`:** lines 183, 422 (standalone main loop).
**Callers of `_bind_worker_rls`:** lines 493, 524, 550, 582, 636, 653, 669, 685, 697, 718 (in-process API via FastAPI).

**No `os.environ` for DB vars** — uses `get_secret("JARVIS_ALPHA_DB_DSN")`.
**No `rls.user_id` reference** — the task tables don't use that GUC.
**No `app.profile_role` reference** — the `child_task_isolation` policy is
not satisfied by this code, but it's an OR'd permissive policy so it
doesn't block access if `task_graph_isolation` passes.

### 11.3 `brain/tasks/watchdog.py`

| File:Line | Code | What it does |
|-----------|------|--------------|
| `watchdog.py:29` | `set_config('jarvis.current_user', 'admin', true)` | `_bind_watchdog_rls` — **WRONG VALUE** |
| `watchdog.py:30` | `set_config('jarvis.role', 'admin', true)` | `_bind_watchdog_rls` — **WRONG VALUE** |

**Caller of `_bind_watchdog_rls`:** line 36 only (once per `check_stuck()` call).
**No `os.environ` for DB vars** — uses `get_secret("JARVIS_ALPHA_DB_DSN")`.
Same pattern as executor.

### 11.4 Anti-pattern check (Stage 5c lesson)

Stage 5c found buddy reading `os.environ` directly instead of
`brain/core/config.py`. Same anti-pattern exists in:

- `watchdog_agent.py:358` — `os.environ["ALPHA_DB_DSN"]` (direct access, no config.py)
- `executor.py:42` — `get_secret("JARVIS_ALPHA_DB_DSN")` (different anti-pattern: uses `get_secret` instead of config.py, AND uses a different env var name)
- `watchdog.py:25` — `get_secret("JARVIS_ALPHA_DB_DSN")` (same)

All three should be standardized to `brain/core/config.py` during cutover.

---

## 12. TD-49 Cross-Check (Task 7)

TD-49 shipped 2026-04-10. Confirming the changes are correct:

### 12.1 `tasks/watchdog.py:111` — INSERT into `alpha_task_events`

```python
await conn.execute(
    """
    INSERT INTO alpha_task_events (
        event_type, graph_id, step_id, message, severity
    )
    VALUES ($1, $2, $3, $4, $5)
    """,
    evt_type,
    row["graph_id"],
    step_id,
    detail,
    pri,
)
```

- **Column name:** `severity` — CORRECT (matches live schema column `severity TEXT NOT NULL DEFAULT 'normal'`)
- **CHECK constraint:** `severity = ANY (ARRAY['low','normal','warning','critical'])` — the code passes `pri` which is set to `'warning'` (line 72) or `'critical'` (line 98). Both are valid.
- **Structured JSON error logging on except branch (lines 122–134):** CONFIRMED — logs `task_event_insert_failed` with `error_class`, `error_message`, `graph_id`, `step_id`.

### 12.2 `executor.py:497` — INSERT into `alpha_task_events` (`TaskGraphExecutor.notify()`)

```python
await conn.execute(
    """
    INSERT INTO alpha_task_events (
        event_type, graph_id, step_id, message, severity
    )
    VALUES ($1, $2::uuid, $3, $4, $5)
    """,
    event_type,
    graph_id,
    sid,
    message,
    severity,
)
```

- **Column name:** `severity` — CORRECT.
- **Values passed:** callers pass `'normal'` (line 631) or `'warning'` (lines 633, 712). All valid per CHECK constraint.
- **Structured JSON error logging on except branch (lines 509–520):** CONFIRMED.

### 12.3 GUC compatibility under writer role

The `alpha_task_events` INSERT paths set `jarvis.current_user='admin'` and
`jarvis.role='admin'` before the INSERT. The RLS policy on
`alpha_task_events` is:

```sql
USING (
  current_setting('jarvis.role', true) = 'platform_admin'
  OR current_setting('jarvis.current_user', true) IS NOT NULL
)
```

The second clause (`IS NOT NULL`) passes because `'admin'` IS NOT NULL.
**The INSERT will succeed under writer role even with the wrong GUC value.**
This is NOT a blocker for `alpha_task_events` specifically — but the GUC
fix to `'platform_admin'` is still needed for `alpha_task_graphs` and
`alpha_task_steps`.

### 12.4 New error log paths under writer role

The structured error logs (e.g., `watchdog.py:123-134`, `executor.py:509-520`)
use `log.error(json.dumps({...}))` — pure Python logging, no DB or GUC
involvement. **These work identically under any DB role.**

---

## 13. Failure-Mode Analysis (Task 9)

For each target service: what happens if `SET ROLE` / `set_config()` fails
after the DSN is flipped to `jarvis_alpha_writer`?

### 13.1 `brain/agents/watchdog_agent.py`

- **SET ROLE usage:** None. This file does not call `SET ROLE`. It calls
  `set_config('rls.user_id', 'system', true)` (line 122) within a
  transaction in `_log_event()`.
- **If `set_config` fails:** The `try/except` at line 154 catches the
  exception and logs `"failed to log watchdog event"`. The watchdog loop
  continues — it does NOT crash or exit. The health checks still run, but
  event logging is silently lost.
- **Blast radius:** LOW. Health checks + kill logic still work. Only
  event history is lost. The loop at `watchdog_loop()` (line 331) catches
  all exceptions at line 351 and sleeps before retrying.
- **Restart behavior:** `KeepAlive.Crashed=true` in the plist. If the
  process exits (uncaught exception), launchd restarts it after 30s
  throttle. But `set_config` failure won't crash the process — it's caught.
- **Detection:** Errors visible in `~/jarvis-alpha/logs/alpha_watchdog_error.log`.
  No alerting path — watchdog monitors others, not itself.

### 13.2 `brain/tasks/executor.py` (standalone `main()`)

- **SET ROLE usage:** None. Uses `set_config('jarvis.current_user', ...)` and
  `set_config('jarvis.role', ...)` via `_bind_executor_rls()`.
- **If `set_config` fails:** `_bind_executor_rls` is called inside
  `run_graph()` (line 183) and the main poll loop (line 422). Neither has
  its own `try/except` around the `set_config` call — the exception
  propagates up.
  - In `run_graph()`: propagates to `_run_graph_with_semaphore()` → caught
    by `asyncio.gather(..., return_exceptions=True)` at line 454. The graph
    is left in `'running'` state (never marked complete/failed). The loop
    continues to the next poll.
  - In the main poll loop (line 422): propagates to the outer `try/except`
    at line 456 → `log.error("Executor loop error: %s", e)`. Loop continues.
- **Blast radius:** MEDIUM. The executor stays alive but graphs would get
  stuck in `'running'` status. The task watchdog (`tasks/watchdog.py`) is
  designed to catch this exact scenario — but it's not running (Q1).
  Visible symptom: tasks stop progressing; no HTTP 500 to users since this
  is a background daemon with no API surface.
- **If GUC succeeds but value is wrong (current situation):** Under
  `jarvisbrain` (BYPASSRLS), the wrong GUC value is invisible. Under
  `jarvis_alpha_writer`, the wrong value causes RLS to filter all rows
  from `alpha_task_graphs` and `alpha_task_steps`. The executor's `SELECT`
  at line 423 returns 0 graphs → it polls forever doing nothing. **This is
  the silent-failure mode — the executor appears healthy but processes
  zero work.** No error is raised, no log is emitted. This is worse than
  a crash because it's invisible.
- **Restart behavior:** `KeepAlive.Crashed=true`. If it crashes, launchd
  restarts after 30s. But the silent-failure mode doesn't crash.
- **Detection:** Only detectable by monitoring: "0 graphs processed in N
  minutes." No such alerting exists today.

### 13.3 `brain/tasks/watchdog.py` (if it were running)

- **SET ROLE usage:** None. Uses `set_config(...)` via `_bind_watchdog_rls()`.
- **If `set_config` fails:** `_bind_watchdog_rls` is called at line 36,
  inside `check_stuck()`. Exception propagates to `main()` line 174 →
  `log.error("Watchdog error: %s", e)`. Loop continues.
- **If GUC value is wrong:** Same silent-failure as executor. The `SELECT`
  at line 37 finds no stuck steps (all filtered by RLS) → nothing to do →
  loop sleeps. **Silently stops detecting stuck tasks.**
- **Blast radius:** LOW-MEDIUM if running — it's a safety net, not a
  primary path. But if both the executor silent-fails AND the watchdog
  silent-fails, there is no automated recovery for stuck graphs.
- **Currently:** NOT RUNNING (no plist). Blast radius is zero.

### 13.4 Summary: silent failure is the dominant risk

The Stage 5b hotfix scenario was a loud failure (500s). The Stage 5d risk
is a **silent failure** — the executor polls, finds 0 graphs (because RLS
filters them), and appears healthy while doing nothing. This is harder to
detect than a crash. **The smoke test MUST verify that the executor sees
actual graph rows under the writer role**, not just that the connection
succeeds.

---

## 14. Risk Table

| # | Finding | Severity | File(s) | Notes |
|---|---------|----------|---------|-------|
| R1 | GUC mismatch: `'admin'` vs `'platform_admin'` — executor/watchdog see 0 rows from `alpha_task_graphs`/`alpha_task_steps` under writer | **BLOCKER** | `executor.py:46-47,480-481`, `watchdog.py:29-30` | Silent failure mode. Fix: change `'admin'` → `'platform_admin'` in 3 bind functions |
| R2 | `TaskGraphExecutor` uses invalid status values (`'complete'`, `'retrying'`, `'halted'`) that violate CHECK constraints | **HIGH** | `executor.py:600,619,639,690,704` | Pre-existing bug, not caused by role flip. In-process API paths are broken regardless. File as separate TD. |
| R3 | No monitoring/alerting for silent executor failure (0 graphs processed) | **HIGH** | `executor.py` (main loop) | If R1 ships undetected, the only signal is "tasks stop progressing" — no log, no metric, no alert |
| R4 | `tasks/watchdog.py` has no LaunchAgent — dead code on host | **MEDIUM** | `tasks/watchdog.py` | If dead code, delete it. If intended to run, it needs a plist before 5d. Decide per Q1. |
| R5 | Env var inconsistency: `ALPHA_DB_DSN` (os.environ) vs `JARVIS_ALPHA_DB_DSN` (get_secret) | **MEDIUM** | `watchdog_agent.py:358`, `executor.py:42`, `watchdog.py:25` | Standardize to `brain/core/config.py` per-service vars during cutover |
| R6 | `app.profile_role` GUC never set — `child_task_isolation` policy unsatisfied | **LOW** | `executor.py` | Not load-bearing (OR'd with `task_graph_isolation`). But worth noting for future FORCE RLS work. |
| R7 | `alpha_task_events` forward migration path undocumented | **LOW** | N/A (DB) | Live schema diverges from checked-in migration. TD-49 fixed the code side. Migration history cleanup is separate. |

---

## 15. Assumptions

1. `pg_stat_activity` showing 2 idle `jarvisbrain` backends = watchdog_agent + executor. Could also include ad-hoc scripts, but timing and count are consistent.
2. `tasks/watchdog.py` is not running. Based on: no plist, no 3rd backend, no `tasks_watchdog` log file.
3. The in-process `TaskGraphExecutor` class is called by FastAPI routes. Not verified by tracing callers — assumed from class docstring and export at module level.
4. `jarvis_alpha_writer` is already a member of `jarvis_alpha_app` (Stage 5b hotfix). Confirmed by the existing discovery doc §5 but not re-verified via `\du+` in this session.
5. The standalone `main()` executor and the in-process `TaskGraphExecutor` share the same tables but may use different pools (standalone uses its own `create_pool`; in-process uses FastAPI's pool which is already on `jarvis_alpha_writer`).

---

## 16. Could Not Verify

1. Whether the `TaskGraphExecutor` in-process API is actively called in production (need to trace FastAPI route imports or check logs).
2. Whether `tasks/watchdog.py` was ever deployed or is a stub that never shipped.
3. The exact contents of `~/jarvis/.secrets` on Brain (secrets access prohibited per CLAUDE.md).
4. Whether `ALPHA_DB_DSN` and `JARVIS_ALPHA_DB_DSN` resolve to the same DSN or different ones (can't read secrets).
5. Whether any ad-hoc psql sessions or CLI tools also set `jarvis.role='admin'` (would be broken by the GUC fix to `'platform_admin'` — needs a grep across the full codebase).

---

**Phase 2 should not start until Ken picks A/B/C and answers Q1–Q5.**
