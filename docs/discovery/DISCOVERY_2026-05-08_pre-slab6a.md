# DISCOVERY 2026-05-08 — Pre-Slab-6a state verification

**Run:** 2026-05-08 morning, Sandbox (jarvissand@jarvis-sandbox), READ-ONLY
**Purpose:** Verify state before Saturday Slab 6a deployment (9 RLS policies)
**Ground-truth references:** `docs/handoffs/HANDOFF_2026-05-07_01.md`, `docs/SLAB6_DEPLOY_PLAN.md`

> **Pre-flight note:** The prompt referenced `HANDOFF_2026-05-07_02.md` and "TD-201".
> A filesystem search for `HANDOFF_2026-05-07_02*` returned **no match**.
> Only `HANDOFF_2026-05-07_01.md` exists in `~/jarvis-alpha/docs/handoffs/`.
> "TD-201" appears nowhere in `~/jarvis-alpha/docs/`. All TD-201/handoff-02 expectations
> are recorded as expectations from the prompt and verified against live state.

---

## §1 — Service health (Brain)

### launchctl service inventory

```
$ ssh jarvisbrain@jarvis-brain.tail40ed36.ts.net 'launchctl list | grep -E "jarvis|temporal|postgres|ollama"'
859	0	com.jarvis.ollama
-	0	com.jarvis.family.chore_reset
66209	0	com.jarvis.alpha.brain
39036	0	com.jarvis.alpha.temporal.server
39079	0	com.jarvis.alpha.temporal.ui
39120	0	com.jarvis.alpha.executor
-	0	com.jarvis.alpha.rotate.buddy
13569	0	homebrew.mxcl.postgresql@16
39114	0	com.jarvis.family.api
39129	0	com.jarvis.alpha.watchdog
66255	0	com.jarvis.alpha.buddy
21380	0	com.jarvis.alpha.power.brain
98474	0	com.jarvis.alpha.fluentbit
-	0	com.jarvis.family.rotate_smoke_pin
-	0	com.jarvis.certrenew
98371	0	com.jarvis.alpha.loki
-	0	com.jarvis.alpha.rotate.brain_service
```

All `com.jarvis.alpha.*` daemons (brain, executor, watchdog, buddy, temporal.server, temporal.ui, fluentbit, loki, power.brain) and `homebrew.mxcl.postgresql@16` show running PIDs (exit code 0).

### `python -m brain` discovery (per prompt verbatim)

```
$ ssh jarvisbrain ... 'ps auxww | grep "python -m brain" | grep -v grep'
no match
```

```
$ ssh jarvisbrain ... 'pgrep -af "python -m brain"' (re-run #2)
(no output, exit 1)
```

Observation: the literal string `python -m brain` is not present in any current `ps` line. The brain service is wrapped by a shell script (see next probe), so the python invocation only surfaces under specific subprocess names (e.g. `brain.tasks.executor`).

### Brain LaunchAgent process (PID 66209)

```
$ ssh jarvisbrain ... 'ps -p 66209 -o etime,command'
    ELAPSED COMMAND
06-18:08:37 /bin/bash /Users/jarvisbrain/jarvis-alpha/scripts/start_alpha_brain.sh
```

`com.jarvis.alpha.brain` runs as a bash wrapper, age 6 days 18h.

### Brain health endpoint (Sandbox → Brain)

```
$ curl -ks https://jarvis-brain.tail40ed36.ts.net:8186/health
{"status":"ok","node":"brain","service":"jarvis-alpha"}
```

Status 200 OK, JSON body confirms node/service.

### Executor process age

```
$ ssh jarvisbrain ... 'ps -o etime,command -p $(pgrep -f "brain.tasks.executor" | head -1)'
    ELAPSED COMMAND
07-16:08:47 /opt/homebrew/Cellar/python@3.12/.../Python -m brain.tasks.executor
```

`brain.tasks.executor` running ~7 days 16h.

### Service health summary

| Service | State | PID | Age |
|---|---|---|---|
| postgresql@16 | running | 13569 | (long-running) |
| com.jarvis.alpha.brain | running | 66209 | 6d 18h |
| com.jarvis.alpha.executor | running | 39120 (parent), python child | 7d 16h |
| com.jarvis.alpha.buddy | running | 66255 | (running) |
| com.jarvis.alpha.watchdog | running | 39129 | (running) |
| com.jarvis.alpha.temporal.server | running | 39036 | (running) |
| com.jarvis.alpha.temporal.ui | running | 39079 | (running) |
| Brain `/health` (8186) | 200 OK | — | — |

---

## §2 — Postgres + approval queue health

### alpha_approval_queue by status

```
$ /opt/homebrew/Cellar/postgresql@16/16.13/bin/psql jarvis_alpha -c \
    "SELECT count(*), status FROM alpha_approval_queue GROUP BY status;"
 cnt |  status
-----+----------
   1 | approved
(1 row)
```

One row in `alpha_approval_queue`, status `approved`.

### alpha_approval_audit by status — query as-prompted

```
$ /opt/homebrew/Cellar/postgresql@16/16.13/bin/psql jarvis_alpha -c \
    "SELECT count(*), status FROM alpha_approval_audit GROUP BY status;"
ERROR:  column "status" does not exist
LINE 1: SELECT count(*), status FROM alpha_approval_audit GRO...
```

The prompt's query failed verbatim. `alpha_approval_audit` schema (per `\d`) shows the column is `decision`, not `status`. CHECK constraint allows `('approved','denied','expired','auto')`.

### alpha_approval_audit by decision (corrected)

```
$ ... -c "SELECT count(*), decision FROM alpha_approval_audit GROUP BY decision ORDER BY decision;"
 cnt | decision
-----+----------
   1 | auto
(1 row)
```

One row, decision `auto`.

### postgres@16 log tail (last 200 lines)

The tail is dominated by pgaudit `AUDIT: SESSION,...,WRITE,UPDATE,TABLE,public.task_queues, ...` lines from the Temporal worker (cluster_membership + task_queues UPDATE/INSERT, ON CONFLICT DO UPDATE).

### 2026-05-08 error scan

```
$ awk '/2026-05-08/,EOF' /opt/homebrew/var/log/postgresql@16.log \
    | grep -iE "expire_pending|ERROR|FATAL|P0003" | grep -v "AUDIT:" | head -30
2026-05-08 08:32:21.317 EDT [47302] ERROR:  column "status" does not exist at character 25
```

Only one ERROR line in the 2026-05-08 slice, and it is the `alpha_approval_audit / status` query I ran 4 lines above (timestamp matches the discovery run). No `expire_pending_approvals` warning, no `P0003` (`APPROVAL_ALREADY_DECIDED`) raise, no FATAL, no other ERROR.

### Verdict (per prompt expectation)

The "TD-201 `expire_pending_approvals` warning from HANDOFF_2026-05-07_02" expectation is unverifiable because handoff #02 does not exist in this repo. **Live observation:** there are zero `expire_pending_approvals`-prefixed warnings or non-self-induced errors in the 2026-05-08 postgres log slice as of this discovery run.

---

## §3 — Slab 6a target table live state (9 policies)

### Table resolution for the 3 not-explicitly-named in the prompt

```
$ ... -c "SELECT polname, polrelid::regclass FROM pg_policy
          WHERE polname IN ('semantic_isolation','vault_access_log_admin','vault_pipeline_admin')
          ORDER BY polname;"
        polname         |       tablename
------------------------+-----------------------
 semantic_isolation     | alpha_semantic_memory
 vault_access_log_admin | vault_access_log
 vault_pipeline_admin   | vault_pipeline
```

### FORCE RLS state for all 9 target tables

```
$ ... -c "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname IN
         ('chat_threads','chat_messages','alpha_conversation_memory','alpha_task_graphs',
          'alpha_task_steps','vault_documents','alpha_semantic_memory','vault_access_log',
          'vault_pipeline');"
          relname          | relrowsecurity | relforcerowsecurity
---------------------------+----------------+---------------------
 alpha_conversation_memory | t              | t
 alpha_semantic_memory     | t              | t
 alpha_task_graphs         | t              | t
 alpha_task_steps          | t              | t
 chat_messages             | t              | t
 chat_threads              | t              | t
 vault_access_log          | t              | t
 vault_documents           | t              | t
 vault_pipeline            | t              | t
(9 rows)
```

All 9 target tables have RLS **enabled** and **forced**.

### pg_policies bodies for the 9 target tables

(Single query against `pg_policies` view — human-readable form. Raw `pg_policy.polqual` was first attempted but returned parse-tree node form which is unreadable; switched to `pg_policies` view, which is what `SLAB6_DEPLOY_PLAN.md` Step 0 itself uses.)

```
         tablename         |       policyname        | permissive  |  cmd   | qual                                                                                                                                       | with_check
---------------------------+-------------------------+-------------+--------+--------------------------------------------------------------------------------------------------------------------------------------------+------------
 alpha_conversation_memory | alpha_memory_isolation  | PERMISSIVE  | ALL    | ((user_id = current_setting('rls.user_id'::text, true)) OR (current_setting('rls.role'::text, true) = 'platform_admin'::text))             | (NULL)
 alpha_conversation_memory | child_content_filter    | RESTRICTIVE | SELECT | child gate via rating_allowed(...)                                                                                                          | (NULL)
 alpha_semantic_memory     | semantic_isolation      | PERMISSIVE  | ALL    | (((user_id)::text = current_setting('rls.user_id'::text, true)) OR (current_setting('rls.role'::text, true) = 'platform_admin'::text))    | (NULL)
 alpha_task_graphs         | child_profile_scope     | RESTRICTIVE | ALL    | child gate via owner_profile                                                                                                                | (NULL)
 alpha_task_graphs         | task_graph_isolation    | PERMISSIVE  | ALL    | ((user_id = current_setting('rls.user_id'::text, true)) OR (current_setting('rls.role'::text, true) = 'platform_admin'::text))             | (NULL)
 alpha_task_steps          | task_step_isolation     | PERMISSIVE  | ALL    | ((user_id = current_setting('rls.user_id'::text, true)) OR (current_setting('rls.role'::text, true) = 'platform_admin'::text))             | (NULL)
 chat_messages             | chat_messages_isolation | PERMISSIVE  | ALL    | (thread_id IN (SELECT id FROM chat_threads WHERE user_id = current_setting('rls.user_id'::text, true)))                                    | same as qual (Shape A-FK)
 chat_messages             | child_messages_scope    | RESTRICTIVE | ALL    | child gate via parent owner_profile                                                                                                         | (NULL)
 chat_threads              | chat_threads_isolation  | PERMISSIVE  | ALL    | (user_id = current_setting('rls.user_id'::text, true))                                                                                      | (user_id = current_setting('rls.user_id'::text, true))
 chat_threads              | child_profile_scope     | RESTRICTIVE | ALL    | child gate via owner_profile                                                                                                                | (NULL)
 vault_access_log          | vault_access_log_admin  | PERMISSIVE  | ALL    | (current_setting('rls.role'::text, true) = 'platform_admin'::text)                                                                          | (NULL)
 vault_documents           | vault_documents_read    | PERMISSIVE  | ALL    | (classification gate, admin OR user with allowed buckets)                                                                                   | (NULL)
 vault_documents           | vault_documents_write   | PERMISSIVE  | ALL    | (current_setting('rls.role'::text, true) = 'platform_admin'::text)                                                                          | (NULL)
 vault_pipeline            | vault_pipeline_admin    | PERMISSIVE  | ALL    | (current_setting('rls.role'::text, true) = 'platform_admin'::text)                                                                          | (NULL)
(14 rows total — 9 target policies + 5 sibling policies on the same tables)
```

### Diff vs. SLAB6_DEPLOY_PLAN.md target shape

| # | Policy | Target change (per plan) | Live qual | Live with_check | Will Slab 6a change? |
|---|---|---|---|---|---|
| 1 | `chat_threads_isolation` | Add admin override (Shape A) — closes TD-196 | user_id only (NO admin) | user_id only (NO admin) | **YES — qual + with_check both gain admin OR** |
| 2 | `chat_messages_isolation` | Add admin override (Shape A-FK) — closes new finding | FK subquery, no admin | FK subquery, no admin | **YES — both clauses gain admin OR** |
| 3 | `alpha_memory_isolation` | Add explicit `with_check` | user_id OR admin | NULL | **YES — adds with_check** |
| 4 | `semantic_isolation` | Add explicit `with_check` | user_id OR admin | NULL | **YES — adds with_check** |
| 5 | `task_graph_isolation` | Add explicit `with_check` | user_id OR admin | NULL | **YES — adds with_check** |
| 6 | `task_step_isolation` | Add explicit `with_check` | user_id OR admin | NULL | **YES — adds with_check** |
| 7 | `vault_access_log_admin` | Add explicit `with_check` | admin-only | NULL | **YES — adds with_check** |
| 8 | `vault_documents_write` | Add explicit `with_check` | admin-only | NULL | **YES — adds with_check** |
| 9 | `vault_pipeline_admin` | Add explicit `with_check` | admin-only | NULL | **YES — adds with_check** |

All 9 target policies present. None already match target shape — all 9 will be modified by 6a (matches plan: "9 policies, single transaction"). No target tables missing, no unexpectedly-named tables. **Pre-state matches HANDOFF_2026-05-07_01.md scope verbatim.**

---

## §4 — Staging database parity (jarvis_alpha_test)

### Existence

```
$ /opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -l | grep -iE "jarvis"
 jarvis              | jarvis      | UTF8 | ...
 jarvis_alpha        | jarvisbrain | UTF8 | ...
 jarvis_alpha_test   | jarvisbrain | UTF8 | ...      ← STAGING DB EXISTS
 jarvis_family       | jarvisbrain | UTF8 | ...
 jarvis_family_test  | jarvisbrain | UTF8 | ...
 ...
```

`jarvis_alpha_test` exists, owner `jarvisbrain`, UTF8.

### Staging policy bodies (same query as §3 vs jarvis_alpha_test)

Returned **14 rows** (same count, same shapes):

```
         tablename         |       policyname        | permissive  | cmd
---------------------------+-------------------------+-------------+--------
 alpha_conversation_memory | alpha_memory_isolation  | PERMISSIVE  | ALL
 alpha_conversation_memory | child_content_filter    | RESTRICTIVE | SELECT
 alpha_semantic_memory     | semantic_isolation      | PERMISSIVE  | ALL
 alpha_task_graphs         | child_profile_scope     | RESTRICTIVE | ALL
 alpha_task_graphs         | task_graph_isolation    | PERMISSIVE  | ALL
 alpha_task_steps          | task_step_isolation     | PERMISSIVE  | ALL
 chat_messages             | chat_messages_isolation | PERMISSIVE  | ALL
 chat_messages             | child_messages_scope    | RESTRICTIVE | ALL
 chat_threads              | chat_threads_isolation  | PERMISSIVE  | ALL
 chat_threads              | child_profile_scope     | RESTRICTIVE | ALL
 vault_access_log          | vault_access_log_admin  | PERMISSIVE  | ALL
 vault_documents           | vault_documents_read    | PERMISSIVE  | ALL
 vault_documents           | vault_documents_write   | PERMISSIVE  | ALL
 vault_pipeline            | vault_pipeline_admin    | PERMISSIVE  | ALL
(14 rows)
```

Qual / with_check texts on staging match prod **byte-for-byte** for all 14 policies (compared via diff of the two psql outputs).

### Staging FORCE RLS state

```
          relname          | relrowsecurity | relforcerowsecurity
---------------------------+----------------+---------------------
 alpha_conversation_memory | t              | t
 alpha_semantic_memory     | t              | t
 alpha_task_graphs         | t              | t
 alpha_task_steps          | t              | t
 chat_messages             | t              | t
 chat_threads              | t              | t
 vault_access_log          | t              | t
 vault_documents           | t              | t
 vault_pipeline            | t              | t
(9 rows)
```

Identical to prod.

### Migration tracker comparison (`schema_migrations`)

```
$ /opt/homebrew/Cellar/postgresql@16/16.13/bin/psql jarvis_alpha -c \
    "SELECT count(*) AS n, max(applied_at) AS latest FROM schema_migrations;"
 n  |            latest
----+-------------------------------
 64 | 2026-05-01 14:29:08.542348-04
(1 row)

$ /opt/homebrew/Cellar/postgresql@16/16.13/bin/psql jarvis_alpha_test -c \
    "SELECT count(*) AS n, max(applied_at) AS latest FROM schema_migrations;"
 n | latest
---+--------
 0 |
(1 row)
```

`schema_migrations` schema is identical (table exists in both DBs), but **prod has 64 rows (latest 2026-05-01), staging has 0 rows**.

### Staging parity verdict (factual)

- Schema parity (RLS on 9 tables, FORCE RLS on all 9): **identical**
- Policy parity (14 bodies on 9 tables): **identical, byte-for-byte**
- Migration history parity: **NOT identical — staging schema_migrations is empty**

The staging DB schema appears to have been built another way (baseline restore? pg_dump?), not via the migrations runner, since the runner would have populated `schema_migrations`. Slab 6a Step 2 ("staging dry run") is **technically unblocked** for policy testing because the policy state is identical — but anyone reading `schema_migrations` for "are we current?" will see false-negative empty rows. This is drift from the plan's implicit assumption that staging mirrors prod end-to-end.

---

## §5 — SECDEF function audit

### Inventory (21 functions, all owner `jarvisbrain`)

```
$ ... -c "SELECT n.nspname, p.proname, p.prosecdef, p.prorettype::regtype
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
          WHERE p.prosecdef = true AND n.nspname NOT IN ('pg_catalog','information_schema')
          ORDER BY n.nspname, p.proname;"
 nspname |             proname              | prosecdef |  prorettype
---------+----------------------------------+-----------+---------------
 public  | bump_memory_access               | t         | integer
 public  | cap_episodic_memory              | t         | integer
 public  | cap_semantic_memory              | t         | integer
 public  | consume_approved_queue_item      | t         | void
 public  | decide_approval                  | t         | record
 public  | enqueue_approval_request         | t         | uuid
 public  | evict_episodic_memory_older_than | t         | integer
 public  | evict_expired_working_memory     | t         | integer
 public  | expire_pending_approvals         | t         | integer
 public  | forget_memory_by_topic           | t         | integer
 public  | forget_working_memory            | t         | integer
 public  | get_buddy_promotion_candidates   | t         | record
 public  | list_active_memory_users         | t         | text[]
 public  | pgaudit_ddl_command_end          | t         | event_trigger
 public  | pgaudit_sql_drop                 | t         | event_trigger
 public  | record_buddy_event               | t         | uuid
 public  | record_watchdog_event            | t         | uuid
 public  | run_buddy_memory_maintenance     | t         | jsonb
 public  | save_semantic_memory             | t         | jsonb
 public  | store_conversation_memory        | t         | uuid
 public  | sync_profile_to_user             | t         | trigger
(21 rows)
```

**`record_watchdog_event` exists.** HANDOFF_2026-05-07_01 §"NEXT SESSION" lists it as a Slab 4 deliverable to be built — but it has already been deployed (migration `20260414_120000_watchdog_secdef.sql` and `20260414_130000_guc_canonicalize.sql` are present in `brain/db/migrations/`).

### Owner check

All 21 SECDEF functions are owned by `jarvisbrain` (confirmed via `pg_get_userbyid(p.proowner)`). `jarvisbrain` is the cluster superuser; superusers carry `BYPASSRLS` by default, so SECDEF functions invoked by `jarvis_alpha_app`/`jarvis_alpha_writer` execute with RLS bypassed regardless of `relforcerowsecurity` on the target.

### `set_config('rls.role'` internal escalation check

A grep across the persisted bodies of all 21 SECDEF functions: **0 matches** for `set_config`. None of these functions internally escalate `rls.role`; they rely entirely on superuser ownership for RLS bypass.

### TD-201 / TD-197 priority functions (full bodies captured, summarized here)

| Function | Target tables (writes) | FORCE RLS on targets | Sets `rls.role` internally? | Owner | Flow path |
|---|---|---|---|---|---|
| `expire_pending_approvals()` | `alpha_approval_queue` (UPDATE), `alpha_approval_audit` (INSERT) | both `t/t` | NO | jarvisbrain (superuser → BYPASSRLS) | UPDATE pending → expired, INSERT audit row, RAISE WARNING on OTHERS |
| `enqueue_approval_request(...)` | `alpha_approval_queue` (INSERT), `alpha_approval_audit` (INSERT) | both `t/t` | NO | jarvisbrain (superuser → BYPASSRLS) | INSERT pending row + INSERT auto audit row |
| `consume_approved_queue_item(p_queue_id uuid)` | `alpha_approval_queue` (UPDATE) | `t/t` | NO | jarvisbrain (superuser → BYPASSRLS) | UPDATE row to `executed`, no exception block |
| `record_watchdog_event(...)` | `alpha_watchdog_events` (INSERT) | `t/t` | NO | jarvisbrain (superuser → BYPASSRLS) | INSERT row, RAISE WARNING on OTHERS |
| `decide_approval(...)` | `alpha_approval_queue` (UPDATE), `alpha_approval_audit` (INSERT) | both `t/t` | NO | jarvisbrain (superuser → BYPASSRLS) | RAISE P0002/P0003/P0004 codes for not-found/already-decided/invalid; RETURN QUERY |
| `record_buddy_event(...)` | `alpha_buddy_events` (INSERT) | `t/t` | NO | jarvisbrain (superuser → BYPASSRLS) | INSERT row, re-raise on any error |

### needs_fix? assessment

| Function | force_rls_on_targets? | sets_rls_role_internally? | needs_fix? |
|---|---|---|---|
| `expire_pending_approvals` | YES | NO | **Depends on TD-201 thesis (handoff #02 missing).** RLS enforcement is only via superuser bypass, not via internal role-set. If the design expectation (per ADR / handoff #02 / TD-201) is "SECDEF must explicitly set `rls.role='platform_admin'` so behavior is correct even if owner is changed", then YES. If the design is "owner = superuser is sufficient", then NO. Ambiguous given missing handoff. |
| `enqueue_approval_request` | YES | NO | Same caveat. Same shape. |
| `consume_approved_queue_item` | YES | NO | Same. |
| `record_watchdog_event` | YES | NO | Same — but note this matches HANDOFF_2026-05-07_01 §TD-197 R5 finding that "watchdog process has zero `rls.role` set calls in code; SECDEF function with internal `set_config('rls.role','platform_admin', true)` is the only clean path." Per handoff R5, this function **should** carry an internal `set_config`. It does not. **Inconsistent with handoff #01's design statement.** |
| `decide_approval` | YES | NO | Same caveat. |
| `record_buddy_event` | YES | NO | Same caveat. |

### Postgres log re-check for `expire_pending_approvals` warnings

```
$ awk '/2026-05-08/,EOF' /opt/homebrew/var/log/postgresql@16.log \
    | grep -iE "expire_pending|ERROR|FATAL|P0003" | grep -v "AUDIT:"
2026-05-08 08:32:21.317 EDT [47302] ERROR:  column "status" does not exist at character 25
```

Only the discovery-induced error. Zero `expire_pending_approvals` runtime warnings on 2026-05-08. The function is invoked by `brain/agents/buddy_agent.py` (per §6) — if it were silently raising `RAISE WARNING`, the logs would show it. They don't.

---

## §6 — Code integration callers (Sandbox grep)

```
$ grep -rn --include="*.py" --include="*.sql" \
    -E "expire_pending_approvals|enqueue_approval_request|consume_approved_queue_item|record_watchdog_event" \
    --exclude-dir=__pycache__ --exclude-dir=.venv --exclude-dir=node_modules
```

**Python callers (production paths):**

```
brain/middleware/approval.py:171:                "SELECT public.consume_approved_queue_item($1::uuid)",
brain/middleware/approval.py:195:                    """SELECT public.enqueue_approval_request(
brain/agents/buddy_agent.py:78:async def _expire_pending_approvals(pool: asyncpg.Pool) -> None:
brain/agents/buddy_agent.py:81:            count = await conn.fetchval("SELECT public.expire_pending_approvals()")
brain/agents/buddy_agent.py:90:    await _expire_pending_approvals(pool)
brain/agents/watchdog_agent.py:123:                "SELECT public.record_watchdog_event($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
brain/routes/watchdog.py:222:            "SELECT public.record_watchdog_event($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::uuid)",
```

Definitions (SQL migrations):

```
brain/db/migrations/20260414_110000_approval_secdef.sql:7:CREATE OR REPLACE FUNCTION public.expire_pending_approvals()
brain/db/migrations/20260414_120000_watchdog_secdef.sql:7:CREATE OR REPLACE FUNCTION public.record_watchdog_event(
brain/db/migrations/20260414_130000_guc_canonicalize.sql:41:CREATE OR REPLACE FUNCTION public.record_watchdog_event(
brain/db/migrations/20260414_140000_approval_rls.sql:31:CREATE OR REPLACE FUNCTION public.enqueue_approval_request(
brain/db/migrations/20260414_140000_approval_rls.sql:73:CREATE OR REPLACE FUNCTION public.consume_approved_queue_item(
```

REVOKE/GRANT discipline confirmed (each migration ends with `REVOKE ALL FROM PUBLIC; GRANT EXECUTE TO jarvis_alpha_app, jarvis_alpha_writer`).

### Direct DML against alpha_watchdog_events

```
$ grep -rn --include="*.py" --include="*.sql" "alpha_watchdog_events" \
    --exclude-dir=__pycache__ --exclude-dir=.venv --exclude-dir=node_modules
```

Match summary (full output captured during run):

| File class | Match type | Notes |
|---|---|---|
| `db/baselines/baseline_2026-04-07_pre_step7*.sql` | CREATE TABLE / INDEX / POLICY / GRANT | Read-only baseline dumps; not runtime DML |
| `brain/db/migrations/20260414_120000_watchdog_secdef.sql` | INSERT inside `record_watchdog_event` body | This is the SECDEF wrapper — expected |
| `brain/db/migrations/20260416_080000_audit_attribution_columns.sql` | ALTER TABLE / COMMENT | Schema migration — expected |
| `brain/db/migrations/20260414_130000_guc_canonicalize.sql` | INSERT inside SECDEF body | Same SECDEF, redefined version |
| `brain/agents/watchdog_agent.py:7` | docstring header (`alpha_watchdog_events.`) | Comment only, no DML |

**Zero direct INSERT/UPDATE/DELETE statements against `alpha_watchdog_events` outside the SECDEF function body.** All runtime writes route through `public.record_watchdog_event()`. Matches HANDOFF_2026-05-07_01 §TD-197 R5 ("watchdog process has zero `rls.role` set calls in code").

---

## §7 — Trait drift verification (jarvis-alpha P-trait)

### `.pre-commit-config.yaml`

`~/jarvis-alpha/.pre-commit-config.yaml` exists, contains:
- ruff (v0.15.12) — ruff-format
- detect-secrets (v1.5.0) with `--baseline .secrets.baseline`, exclude pattern for the baseline file
- local hook `jarvis-namespace` (TD-X24 + TD-X25) calling `bash .jarvis-hooks/pre-commit`
- local hook `jarvis-force-push-block` (pre-push) calling `.jarvis-hooks/pre-push`

### `.git/hooks` directory

```
$ ls -la /Users/jarvissand/jarvis-alpha/.git/hooks/ | grep -v sample
-rwxr-xr-x  1 jarvissand staff  1251 May  4 16:43 commit-msg
-rwxr-xr-x  1 jarvissand staff   643 May  6 21:21 pre-commit
-rwxr-xr-x  1 jarvissand staff  3723 May  4 16:43 pre-commit.legacy
-rwxr-xr-x  1 jarvissand staff   641 May  6 21:21 pre-push
```

`pre-commit`, `pre-push`, `commit-msg` all installed; `pre-commit.legacy` retained as fallback.

### `jarvisalpha_commit.sh` line ~310

```
295:    [[ -z "$staged_path" ]] && continue
...
303:  if (( ${#forbidden_staged[@]} > 0 )); then
304:    step_fail "git commit" "forbidden paths staged"
...
309:  commit_start=$SECONDS
310:  git commit -m "$COMMIT_MSG" >/dev/null 2>&1 || { step_fail "git commit" "commit failed"; exit 1; }
311:  HEAD_AFTER=$(git rev-parse --short HEAD)
```

**Confirmed: line 310 is a raw `git commit -m "$COMMIT_MSG"`.** No branching, no `--no-verify`. With the `pre-commit` hook installed, this will reject when invoked on `main` or `master`, matching HANDOFF_2026-05-07_01 §"TRAIT DRIFT" claim.

### `jarvis_branch` / `jarvis_pr` definitions

```
$ type jarvis_branch
jarvis_branch is /Users/jarvissand/jarvis-standards/scripts/jarvis_branch
$ type jarvis_pr
jarvis_pr is /Users/jarvissand/jarvis-standards/scripts/jarvis_pr
```

Both resolve to scripts in `~/jarvis-standards/scripts/` (not shell functions). On `$PATH`.

### Recent main merges

```
$ git log --oneline --first-parent -20 main
18617e5 docs(handoff): 2026-05-07 #01 — RLS audit, Slab 6a scope=9, TD-197, trait drift (#76)
f5510ed docs(rls): SLAB6 scope=9 policies, TD-197 watchdog deferred to SLAB4 (#75)
f791544 ci: propagate substrate pre-push hook (TD-X33) (#74)
05c158f ci: adopt JARVIS pre-commit + CI workflow (Phase 3)
786c7bf ci: add PR-base staleness workflow (TD-X23) (#71)
b3f6385 docs(handoff): 2026-05-01 #01 — RLS Step 7 specs locked, Slabs 5 + 5.5 shipped
f5510ed... (truncated; consistent pattern)
```

Recent commits with `(#NN)` suffixes — PR-squash style. `05c158f` ("ci: adopt JARVIS pre-commit + CI workflow (Phase 3)") was direct (no PR# suffix); `f791544` and onward all PR-squash.

### ADR-0005 §15.2 / "direct to main" exception text

Grep on `~/jarvis-standards/docs/adr/ADR-0005-adopt-multi-writer-coordination-model.md` for `15.2` returned **no matches**. ADR-0005's section structure (top-level headings):

```
1   # ADR-0005: Adopt multi-writer coordination model
11  ## Context
42  ## Decision
46  ### Layer 1 — coordination
60  ### Layer 2 — provenance
84  ### Layer 3 — branch namespace
95  ### Trait system
121 ## Consequences
...
196 ### 2026-05-05 — Force-push semantics on agent branches (§6.1.1)
217 ## References
```

ADR-0005 has no §15.2 directly. The `pre-commit` hook prints `"direct commits to main are forbidden per ADR-0005 §15.2 #11"` — but the actual `§15.2 #11` rule lives in `~/jarvis-standards/docs/DEPLOYMENT.md` line 975 (`### 15.2 Multi-writer / commits **[NEW per ADR-0005]**`). The hook's user-visible message conflates ADR-0005 (which sponsors the rule) with DEPLOYMENT.md (which defines `§15.2 #11` itself). The hook's source comments correctly cite `DEPLOYMENT.md §15.2 #11`; only the user-visible error string says ADR-0005.

### Trait conclusion (evidence-based)

- **jarvis-alpha is currently P-trait.** Pre-commit framework installed (`.pre-commit-config.yaml`), JARVIS namespace hook + force-push block in `.git/hooks/`, recent merges via PR squash.
- **`jarvisalpha_commit.sh` is blocked on raw `git commit` at line 310** when invoked on `main` (the new pre-commit hook rejects with the §15.2 #11 message). It will succeed on a feature branch.
- **Nomenclature drift:** the pre-commit user-visible message says "ADR-0005 §15.2 #11"; the actual `§15.2 #11` is in DEPLOYMENT.md. ADR-0005 sponsors the rule but does not contain `15.2` literally. Cosmetic.

---

## §8 — Smoke harness state

### File presence + line count

```
$ ls -la /Users/jarvissand/jarvis-alpha/brain/db/tests/rls_smoke.sql
-rw-r--r--  1 jarvissand staff  9437 May  7 17:52 .../rls_smoke.sql
$ wc -l .../rls_smoke.sql
     237 .../rls_smoke.sql
```

237 lines (matches HANDOFF_2026-05-07_01 expectation).

### Case markers — prompt query vs. actual format

```
$ grep -c "^-- Case" .../rls_smoke.sql
0
```

**Prompt's exact regex returned 0.** The actual case-header format in this file is `\echo === Case N: ...` (psql `\echo` directives), not SQL comments. Re-running with the correct anchor:

```
$ grep -nE "Case [0-9]+:" .../rls_smoke.sql
28:\echo === Case 1: platform_admin sees all Shape A rows ===
45:\echo === Case 2: user_a sees only own Shape A rows ===
67:\echo === Case 3: child with age_8_plus ceiling ===
86:\echo === Case 4: All GUCs reset = fail-closed ===
100:\echo === Case 5: user role on Shape B = 0 rows ===
118:\echo === Case 6: platform_admin sees all Shape B rows ===
138:\echo === Case 7: user_a sees only own thread messages (Shape A-FK) ===
170:\echo === Case 8: FK isolation - user_a cannot see messages with user_b parent ===
189:\echo === Case 9: chat_messages admin override READ ===
207:\echo === Case 10: chat_messages admin override WRITE ===
$ grep -cE "^\\\\echo === Case" .../rls_smoke.sql
10
```

**10 cases present (matches HANDOFF expectation).** Cases 1-8 baseline + Cases 9-10 added 2026-05-07 for chat_messages admin override (per HANDOFF §"SMOKE HARNESS").

### `run_smoke.sh` presence

```
$ ls -la /Users/jarvissand/jarvis-alpha/scripts/run_smoke.sh
-rwxr-xr-x  1 jarvissand staff  6764 May  1 16:43 .../run_smoke.sh
```

Present, executable, mtime 2026-05-01 (Slab 5.5 ship — matches PR f115634).

The harness was **not executed** per prompt constraint.

---

# FINAL SUMMARY

## GREEN — matches handoff expectations

- **Brain services healthy.** All `com.jarvis.alpha.*` LaunchAgents running; `/health` returns 200 OK with `{"status":"ok"}`; executor running 7d 16h. (§1)
- **9 RLS target policies all present, all on FORCE RLS tables, all in pre-Slab-6a state matching the plan's expected pre-state.** Three previously-unidentified target tables resolved: `semantic_isolation` → `alpha_semantic_memory`, `vault_access_log_admin` → `vault_access_log`, `vault_pipeline_admin` → `vault_pipeline`. All 9 policies will be modified by 6a; none unexpectedly already-canonical, none missing. (§3)
- **Staging DB `jarvis_alpha_test` exists.** All 14 policies on the 9 target tables byte-for-byte identical to prod; FORCE RLS state identical; ready for Slab 6a Step 2 dry run from a policy-state perspective. (§4)
- **Trait drift confirmed P-trait.** `.pre-commit-config.yaml` + namespace + force-push hooks installed; recent merges PR-squash; `jarvis_branch` / `jarvis_pr` resolve to `~/jarvis-standards/scripts/`. Matches HANDOFF_2026-05-07_01 §"TRAIT DRIFT". (§7)
- **`jarvisalpha_commit.sh` line 310 is raw `git commit`** — confirmed; will fail on `main`, requires feature branch first. Matches handoff claim. (§7)
- **Smoke harness shipped at 237 lines, 10 cases.** Cases 1–10 present; `run_smoke.sh` executable. (§8)
- **All four TD-197/TD-201 priority SECDEF functions exist and are wired.** `expire_pending_approvals`, `enqueue_approval_request`, `consume_approved_queue_item`, `record_watchdog_event` all present in DB; callers in `brain/agents/`, `brain/middleware/`, `brain/routes/`. REVOKE/GRANT discipline applied per migration. (§5, §6)
- **Zero direct DML against `alpha_watchdog_events` outside SECDEF.** All runtime writes route through `record_watchdog_event()`. Matches HANDOFF_2026-05-07_01 §TD-197 R5. (§6)
- **No `expire_pending_approvals` warnings or runtime errors** in the 2026-05-08 postgres log slice (only one self-induced ERROR from this discovery's bad column reference). The function is being called (via `buddy_agent.py`) but is producing no log noise. (§2, §5)
- **`record_watchdog_event` already deployed.** Migrations `20260414_120000_watchdog_secdef.sql` + `20260414_130000_guc_canonicalize.sql` already created/redefined it; the function exists in prod. HANDOFF_2026-05-07_01 §"NEXT SESSION" listed it as a Slab 4 to-build deliverable, but it is in fact already shipped. Either the handoff was outdated on this point or "Slab 4 deliverable" means a future REWRITE, not a from-scratch creation. (§5, §6)

## YELLOW — drift from expectations, low risk

- **`HANDOFF_2026-05-07_02.md` and "TD-201" referenced by the prompt do not exist in the repo.** Only `HANDOFF_2026-05-07_01.md` is present in `docs/handoffs/`. Cross-references to handoff #02 and TD-201 in the prompt cannot be ground-truth-verified; they are recorded as "expectation per prompt only." (§intro, §2, §5)
- **Staging `schema_migrations` table is empty (0 rows) while prod has 64 rows.** Schema/policy parity is fine, but the migration tracker was never populated on staging — looks like a baseline-restored DB rather than a runner-built one. Slab 6a Step 2 dry run is still feasible (policy state matches), but anyone scripting "are migrations current?" against staging will get a false negative. (§4)
- **`alpha_approval_audit` schema column is `decision`, not `status` (per the prompt's verbatim query).** The prompt's `GROUP BY status` query failed verbatim. Corrected query (`GROUP BY decision`) returned `1 | auto`. The prompt's expectation was implicitly `status` — actual schema diverges. (§2)
- **Pre-commit hook user-visible message says "ADR-0005 §15.2 #11"; actual `§15.2 #11` lives in DEPLOYMENT.md (ADR-0005 has no `15.2` text).** Cosmetic nomenclature drift; the rule is enforced correctly. (§7)
- **Smoke harness Case markers are `\echo === Case N: ...`, not `^-- Case ...`.** Prompt's verbatim `grep -c "^-- Case"` returned 0; actual count via `grep -cE "^\\\\echo === Case"` returns 10. Cosmetic — harness content is correct. (§8)
- **`com.jarvis.alpha.brain` runs as `bash start_alpha_brain.sh`, not `python -m brain.*`.** Prompt's `pgrep -af "python -m brain"` returned no match; brain process is wrapped by a shell script. The actual brain server is reachable on port 8186 and `/health` returns OK, so this is a discoverability quirk, not a service issue. (§1)

## RED — blocks 6a deployment OR raises data integrity concern

- **None identified.** No live ERROR/FATAL/expire_pending_approvals warnings on 2026-05-08; all 9 target policies in pre-Slab-6a expected state; staging DB exists with identical policy state; smoke harness shipped at 10 cases; SECDEF fleet in place; pre-commit gating active.
- **One dependent caveat (not RED, but a decision the operator must make):** the SECDEF fleet relies entirely on `jarvisbrain` being a superuser with BYPASSRLS to bypass FORCE RLS on target tables. **None of the 21 SECDEF functions sets `rls.role` internally via `set_config`.** HANDOFF_2026-05-07_01 §TD-197 R5 explicitly stated that the canonical fix is `record_watchdog_event` "with internal `set_config('rls.role','platform_admin', true)`" — which is not what is deployed. The function works (RLS is bypassed via owner), but it does not match the design statement in handoff #01. If "TD-201" in the missing handoff #02 codified an expectation that SECDEF must internally escalate, the deployed code does not satisfy it. **This does not block Slab 6a (6a does not touch SECDEF bodies)** but is worth surfacing to Ken before Slab 4 begins. (§5)

---

**Pre-flight discovery complete. Saturday Slab 6a deploy: GO / NO-GO requires Ken's review of RED items above. Staging rehearsal status: READY — policy/schema parity verified; staging `schema_migrations` is empty but does not block the dry run.**
