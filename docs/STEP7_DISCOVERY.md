# Step 7 Discovery — RLS, GUC Usage, and Background Writers

**Scope:** Read-only code discovery. No migrations written, no files modified.
**Date:** 2026-04-08

---

## 1. Agent Files — Full SQL Inventory

### 1a. `brain/agents/buddy_agent.py`

| Line | Statement | Table | Context |
|------|-----------|-------|---------|
| 35–46 | `INSERT INTO alpha_buddy_events (user_id, event_type, title, body, priority) VALUES ($1,$2,$3,$4,$5)` | alpha_buddy_events | Background write, no GUC set before INSERT |
| 52–59 | `UPDATE alpha_approval_queue SET status='expired' WHERE status='pending' AND expires_at < NOW() RETURNING ...` | alpha_approval_queue | Background write, no GUC set |
| 65–76 | `INSERT INTO alpha_approval_audit (...) SELECT ... FROM alpha_approval_queue WHERE id = ANY($1)` | alpha_approval_audit | Background write, no GUC set |
| 101–103 | `SELECT DISTINCT user_id FROM alpha_conversation_memory` | alpha_conversation_memory | Read, no GUC set |
| 139–147 | `DELETE FROM alpha_conversation_memory WHERE user_id=$1 AND tier='episodic' AND created_at < now()-interval '30 days'` | alpha_conversation_memory | Background write, no GUC set |
| 150–161 | `DELETE FROM alpha_conversation_memory WHERE id IN (SELECT id ... OFFSET 1000)` | alpha_conversation_memory | Background write, cap enforcement |
| 163–175 | `DELETE FROM alpha_conversation_memory WHERE id IN (SELECT id ... ORDER BY importance_score ASC OFFSET 200)` | alpha_conversation_memory | Background write, semantic cap |
| 188–191 | `SELECT set_config('jarvis.current_user', $1, true)` | — | GUC write (transaction-local), sets user identity |
| 192–202 | `SELECT id, summary FROM alpha_conversation_memory WHERE user_id=$1 AND tier='working' AND created_at < now()-interval '20 hours'` | alpha_conversation_memory | Read, within same connection as GUC set |

**create_pool call:**
- Line 228: `asyncpg.create_pool(dsn, min_size=1, max_size=3)` — DSN from `os.environ.get("ALPHA_DB_DSN")`

**Key observation:** Most writes in buddy_agent (approval expiry, memory evictions, buddy events) happen on connections acquired *before* any `set_config` call. Only the aging-check SELECT on line 192 is preceded by a `set_config` on line 188. The eviction/cap-enforcement DELETEs on lines 139–175 have no GUC set at all.

---

### 1b. `brain/agents/watchdog_agent.py`

| Line | Statement | Table | Context |
|------|-----------|-------|---------|
| 122 | `SELECT set_config('rls.user_id', 'system', true)` | — | GUC write, inside `conn.transaction()` |
| 123–144 | `INSERT INTO alpha_watchdog_events (...) VALUES ($1,...,$11)` | alpha_watchdog_events | Background write, preceded by `set_config('rls.user_id','system')` |
| 204–216 | `SELECT name, health_endpoint, node_type FROM alpha_node_registry WHERE ...` | alpha_node_registry | Read, no GUC set |

**create_pool call:**
- Line 359: `asyncpg.create_pool(dsn, min_size=1, max_size=3)` — DSN from `os.environ["ALPHA_DB_DSN"]`

---

### 1c. `brain/tasks/executor.py`

#### Standalone process (`main()` / `run_graph()`)

| Line | Statement | Table | Context |
|------|-----------|-------|---------|
| 46–47 | `set_config('jarvis.current_user','admin',true)` + `set_config('jarvis.role','admin',true)` | — | `_bind_executor_rls()` — called before all graph/step queries |
| 99–116 | `SELECT s.* FROM alpha_task_steps WHERE graph_id=$1 AND status='pending' AND NOT EXISTS(...)` | alpha_task_steps | Read, after GUC bind |
| 184–191 | `UPDATE alpha_task_graphs SET status='running', started_at=now()` | alpha_task_graphs | Write, after GUC bind |
| 280–288 | `UPDATE alpha_task_steps SET status='queued', approval_status='pending'` | alpha_task_steps | Write |
| 291–298 | `UPDATE alpha_task_steps SET status='running', started_at=now()` | alpha_task_steps | Write |
| 326–337 | `UPDATE alpha_task_steps SET status='completed', output=$2::jsonb` | alpha_task_steps | Write |
| 344–365 | `UPDATE alpha_task_steps SET status='pending'/'failed', retry_count/error_message` | alpha_task_steps | Write |
| 377–387 | `UPDATE alpha_task_steps SET status='skipped'` (downstream cascade) | alpha_task_steps | Write |
| 420–431 | `SELECT id FROM alpha_task_graphs WHERE status IN ('pending','running') LIMIT $1` | alpha_task_graphs | Read |
| 433–443 | `SELECT DISTINCT g.id FROM alpha_task_graphs g JOIN alpha_task_steps s ON ...` | alpha_task_graphs, alpha_task_steps | Read |

#### `TaskGraphExecutor` class (in-process FastAPI use)

| Line | Statement | Table | Context |
|------|-----------|-------|---------|
| 480–481 | `set_config('jarvis.current_user','admin',true)` + `set_config('jarvis.role','admin',true)` | — | `_bind_worker_rls()` — repeated before every acquire |
| 495–507 | `INSERT INTO alpha_task_events (event_type, graph_id, step_id, message, priority)` | alpha_task_events | Write, after GUC bind |
| 512–521 | `SELECT id, depends_on, status FROM alpha_task_steps WHERE graph_id=$1` | alpha_task_steps | Read |
| 540–548 | `UPDATE alpha_task_steps SET status='running', started_at=...` | alpha_task_steps | Write |
| 549–558 | `SELECT id, graph_id, label, ... FROM alpha_task_steps WHERE id=$1` | alpha_task_steps | Read |
| 585–596 | `UPDATE alpha_task_steps SET retry_count=retry_count+1, status='retrying', error=$2` | alpha_task_steps | Write |
| 599–604 | `UPDATE alpha_task_steps SET status='pending'` | alpha_task_steps | Write |
| 609–616 | `UPDATE alpha_task_steps SET status='halted', error=$2` | alpha_task_steps | Write |
| 626–637 | `UPDATE alpha_task_steps SET status='complete', output=$2::jsonb` | alpha_task_steps | Write |
| 643–650 | `UPDATE alpha_task_graphs SET status='running', started_at=...` | alpha_task_graphs | Write |
| 658–666 | `SELECT status FROM alpha_task_steps WHERE graph_id=$1` | alpha_task_steps | Read |
| 673–682 | `UPDATE alpha_task_graphs SET status='complete'` | alpha_task_graphs | Write |
| 685–694 | `UPDATE alpha_task_graphs SET status='halted'` | alpha_task_graphs | Write |
| 706–714 | `UPDATE alpha_task_graphs SET status='pending' WHERE status='running'` | alpha_task_graphs | Write (`recover_stuck_graphs`) |

**create_pool call:**
- Line 406: `asyncpg.create_pool(dsn, min_size=2, max_size=5)` — DSN from `get_secret("JARVIS_ALPHA_DB_DSN")` via secrets manager

---

## 2. GUC Usage Map

### `rls.user_id`

| File | Line | Context | Read/Write |
|------|------|---------|-----------|
| brain/db/rls.py | 112 | `set_config('rls.user_id', user_id, true)` in `rls_connection()` | Write |
| brain/agents/watchdog_agent.py | 122 | `set_config('rls.user_id', 'system', true)` inside transaction | Write |
| brain/routes/watchdog.py | 224 | `set_config('rls.user_id', 'system', true)` — route handler for manual watchdog writes | Write |
| brain/db/migrations/012_watchdog_events.sql | 53 | `WITH CHECK (current_setting('rls.user_id', true) = 'system')` — write gate on alpha_watchdog_events | Read (policy) |
| brain/db/migrations/015_chat_rls_fix.sql | 13–14 | `USING/WITH CHECK (user_id = current_setting('rls.user_id', true))` — chat_threads isolation | Read (policy) |
| brain/db/migrations/015_chat_rls_fix.sql | 36, 42 | `WHERE user_id = current_setting('rls.user_id', true)` — chat_messages subquery | Read (policy) |

### `jarvis.current_user`

| File | Line | Context | Read/Write |
|------|------|---------|-----------|
| brain/db/rls.py | 105 | `set_config('jarvis.current_user', user_id, true)` in `rls_connection()` | Write |
| brain/memory/memory.py | 131 | `set_config('jarvis.current_user', user_id, true)` — `_get_semantic()` | Write |
| brain/memory/memory.py | 160 | `set_config('jarvis.current_user', user_id, true)` — `_get_episodic()` | Write |
| brain/memory/memory.py | 259 | `set_config('jarvis.current_user', user_id, true)` — `store()` | Write |
| brain/memory/memory.py | 295 | `set_config('jarvis.current_user', user_id, true)` — `save_semantic()` | Write |
| brain/memory/memory.py | 324 | `set_config('jarvis.current_user', user_id, true)` — `promote_to_semantic()` | Write |
| brain/tasks/executor.py | 46 | `set_config('jarvis.current_user', 'admin', true)` — `_bind_executor_rls()` | Write |
| brain/tasks/executor.py | 480 | `set_config('jarvis.current_user', 'admin', true)` — `_bind_worker_rls()` | Write |
| brain/tasks/watchdog.py | 29 | `set_config('jarvis.current_user', 'admin', true)` — `_bind_watchdog_rls()` | Write |
| brain/agents/buddy_agent.py | 189 | `set_config('jarvis.current_user', user_id, true)` — aging-check loop | Write |
| brain/routes/dev.py | 54, 272 | `set_config('jarvis.current_user', user_id, true)` — dev route direct usage | Write |
| brain/db/migrations/006_task_graphs.sql | 64, 72 | `current_setting('jarvis.current_user', TRUE)` — task_graphs_isolation policy | Read (policy) |
| brain/db/migrations/008_buddy_events.sql | 38 | `current_setting('jarvis.current_user', TRUE)` — buddy_events_isolation | Read (policy) |
| brain/db/migrations/008b_task_events.sql | 35 | `current_setting('jarvis.current_user', TRUE) = 'admin'` — task_events_isolation | Read (policy) |
| brain/db/migrations/003_memory_tiers.sql | 36 | `user_id::text = current_setting('jarvis.current_user')` — semantic_isolation | Read (policy) |
| brain/db/schema.sql | 149 | `current_setting('jarvis.current_user', true)` — legacy vault_child_filter | Read (policy) |

### `jarvis.role`

| File | Line | Context | Read/Write |
|------|------|---------|-----------|
| brain/db/rls.py | 108 | `set_config('jarvis.role', jarvis_role, true)` — values: `'platform_admin'` or `'user'` | Write |
| brain/tasks/executor.py | 47, 481 | `set_config('jarvis.role', 'admin', true)` | Write |
| brain/tasks/watchdog.py | 30 | `set_config('jarvis.role', 'admin', true)` | Write |
| brain/routes/dev.py | 58, 276 | `set_config('jarvis.role', ..., true)` | Write |
| brain/db/migrations/006_task_graphs.sql | 65, 73 | `current_setting('jarvis.role', TRUE) = 'admin'` — task_graphs_isolation / task_steps_isolation | Read (policy) |
| brain/db/migrations/008_buddy_events.sql | 39 | `current_setting('jarvis.role', TRUE) = 'admin'` — buddy_events_isolation | Read (policy) |

### `app.profile_role`

| File | Line | Context | Read/Write |
|------|------|---------|-----------|
| brain/db/rls.py | 95 | `set_config('app.profile_role', profile_role, true)` — values: `'admin'` or `'child'` | Write |
| brain/db/migrations/009_child_profiles.sql | 53, 61, 72, 80, 88, 95, 102, 109 | `current_setting('app.profile_role', true) = 'admin'` — child isolation policies | Read (policy) |
| brain/db/migrations/014_vault_rls_v1.sql | 47, 50, 57, 66, 75 | `current_setting('app.profile_role', true)` — vault read/write policies | Read (policy) |
| brain/db/migrations/015_chat_rls_fix.sql | 19, 23, 49, 56 | `current_setting('app.profile_role', true) = 'admin'` — chat thread/message child isolation | Read (policy) |

### `jarvis.is_admin` (referenced in one policy, never written by application code)

| File | Line | Context | Read/Write |
|------|------|---------|-----------|
| brain/db/migrations/003_memory_tiers.sql | 37 | `current_setting('jarvis.is_admin', true) = 'true'` — semantic_isolation fallback | Read (policy) |

### `app.profile_id` / `app.max_rating` / `app.workspace_id` / `app.user_id`

| GUC | File | Line | Context | Read/Write |
|-----|------|------|---------|-----------|
| app.user_id | brain/db/rls.py | 89 | `set_config('app.user_id', user_id, true)` | Write |
| app.profile_id | brain/db/rls.py | 92 | `set_config('app.profile_id', user_id, true)` | Write |
| app.profile_id | brain/db/migrations/009_child_profiles.sql | 54, 64 | `current_setting('app.profile_id', true)` — child_thread_isolation | Read (policy) |
| app.profile_id | brain/db/migrations/015_chat_rls_fix.sql | 20, 24, 52, 59 | `current_setting('app.profile_id', true)` — child isolation policies | Read (policy) |
| app.max_rating | brain/db/rls.py | 98 | `set_config('app.max_rating', max_rating, true)` | Write |
| app.max_rating | brain/db/migrations/009_child_profiles.sql | 73, 81 | `rating_level(current_setting('app.max_rating', true))` | Read (policy) |
| app.workspace_id | brain/db/rls.py | 101 | `set_config('app.workspace_id', workspace_id, true)` | Write |

---

## 3. RLS Policies

### `alpha_conversation_memory` (working/episodic memory)

No explicit ENABLE RLS found in migrations for this table directly, but writes go through `jarvis.current_user` in memory.py.

> **Note:** `alpha_conversation_memory` appears in `buddy_agent.py` bulk DELETEs with no GUC set.

### `alpha_semantic_memory`

| Migration | Policy Name | Table | Operation | GUC Checked |
|-----------|-------------|-------|-----------|-------------|
| 003_memory_tiers.sql:31 | `semantic_isolation` | alpha_semantic_memory | FOR ALL | `jarvis.current_user` (user_id match) OR `jarvis.is_admin = 'true'` |

ENABLE ROW LEVEL SECURITY: `003_memory_tiers.sql:31`

### `alpha_task_graphs`

| Migration | Policy Name | Table | Operation | GUC Checked |
|-----------|-------------|-------|-----------|-------------|
| 006_task_graphs.sql:62 | `task_graphs_isolation` | alpha_task_graphs | FOR ALL (no FOR clause = all ops) | `jarvis.current_user` (created_by match) OR `jarvis.role = 'admin'` |
| 009_child_profiles.sql:92 | `child_task_isolation` | alpha_task_graphs | FOR ALL | `app.profile_role = 'admin'` |

ENABLE ROW LEVEL SECURITY: `006_task_graphs.sql:59`, `009_child_profiles.sql:115`

### `alpha_task_steps`

| Migration | Policy Name | Table | Operation | GUC Checked |
|-----------|-------------|-------|-----------|-------------|
| 006_task_graphs.sql:68 | `task_steps_isolation` | alpha_task_steps | FOR ALL | `jarvis.current_user` via graph subquery OR `jarvis.role = 'admin'` |

ENABLE ROW LEVEL SECURITY: `006_task_graphs.sql:60`

### `alpha_task_events`

| Migration | Policy Name | Table | Operation | GUC Checked |
|-----------|-------------|-------|-----------|-------------|
| 008b_task_events.sql:34 | `task_events_isolation` | alpha_task_events | FOR ALL | `jarvis.current_user = 'admin'` (literal string) |

ENABLE ROW LEVEL SECURITY: `008b_task_events.sql:32`

### `alpha_buddy_events`

| Migration | Policy Name | Table | Operation | GUC Checked |
|-----------|-------------|-------|-----------|-------------|
| 008_buddy_events.sql:34 | `buddy_events_isolation` | alpha_buddy_events | FOR ALL | `jarvis.current_user` via graph subquery OR `jarvis.role = 'admin'` |

ENABLE ROW LEVEL SECURITY: `008_buddy_events.sql:32`

> **Note:** There are two versions of alpha_buddy_events. Migration `005_buddy_events.sql` creates a simpler schema (no graph_id FK). Migration `008_buddy_events.sql` creates a task-graph-linked version with RLS. The one active in production depends on apply order — both share the table name `alpha_buddy_events`. The `005` version has no RLS.

### `alpha_watchdog_events`

| Migration | Policy Name | Table | Operation | GUC Checked |
|-----------|-------------|-------|-----------|-------------|
| 012_watchdog_events.sql:47 | `watchdog_events_read` | alpha_watchdog_events | FOR SELECT | USING(true) — unrestricted read |
| 012_watchdog_events.sql:51 | `watchdog_events_system_write` | alpha_watchdog_events | FOR INSERT | `rls.user_id = 'system'` |

ENABLE ROW LEVEL SECURITY: `012_watchdog_events.sql:45` (no FORCE)

### `chat_threads`

| Migration | Policy Name | Table | Operation | GUC Checked |
|-----------|-------------|-------|-----------|-------------|
| 009_child_profiles.sql:50 → dropped by 015 | `child_thread_isolation` (original) | chat_threads | FOR ALL | `app.profile_role = 'admin'` OR `owner_profile = app.profile_id` |
| 015_chat_rls_fix.sql:11 | `chat_threads_isolation` | chat_threads | FOR ALL | `user_id = rls.user_id` (WITH CHECK added) |
| 015_chat_rls_fix.sql:16 | `child_thread_isolation` (recreated) | chat_threads | FOR ALL | `app.profile_role = 'admin'` OR `owner_profile = app.profile_id` (WITH CHECK added) |

ENABLE ROW LEVEL SECURITY: `009_child_profiles.sql:113`

### `chat_messages`

| Migration | Policy Name | Table | Operation | GUC Checked |
|-----------|-------------|-------|-----------|-------------|
| 009_child_profiles.sql:58 → dropped by 015 | `child_message_isolation` (original) | chat_messages | FOR ALL | `app.profile_role = 'admin'` OR thread in child's threads via `app.profile_id` |
| 009_child_profiles.sql:69 | `child_content_rating` | chat_messages | FOR SELECT | `app.profile_role = 'admin'` OR `rating_level(content_rating) <= rating_level(app.max_rating)` |
| 015_chat_rls_fix.sql:31 | `chat_messages_isolation` | chat_messages | FOR ALL | thread_id in threads where `user_id = rls.user_id` (WITH CHECK added) |
| 015_chat_rls_fix.sql:46 | `child_message_isolation` (recreated) | chat_messages | FOR ALL | `app.profile_role = 'admin'` OR thread in child's threads via `app.profile_id` (WITH CHECK added) |

ENABLE ROW LEVEL SECURITY: `009_child_profiles.sql:114`

### `alpha_dream_sessions`

| Migration | Policy Name | Table | Operation | GUC Checked |
|-----------|-------------|-------|-----------|-------------|
| 009_child_profiles.sql:99 | `child_dream_isolation` | alpha_dream_sessions | FOR ALL | `app.profile_role = 'admin'` |

ENABLE ROW LEVEL SECURITY: `009_child_profiles.sql:116`

### `alpha_dream_steps`

| Migration | Policy Name | Table | Operation | GUC Checked |
|-----------|-------------|-------|-----------|-------------|
| 009_child_profiles.sql:106 | `child_dream_step_isolation` | alpha_dream_steps | FOR ALL | `app.profile_role = 'admin'` |

ENABLE ROW LEVEL SECURITY: `009_child_profiles.sql:117`

### `vault_documents`

| Migration | Policy Name | Table | Operation | GUC Checked |
|-----------|-------------|-------|-----------|-------------|
| schema.sql:144 | `vault_child_filter` (legacy) | vault_documents | FOR SELECT | `NOT (is_child AND classification NOT IN ('10_PUBLIC','20_PROJECTS'))` via alpha_users lookup using `jarvis.current_user` |
| 014_vault_rls_v1.sql:42 | `vault_documents_read` | vault_documents | FOR SELECT | `app.profile_role = 'admin'` (tiers 10–40) OR `app.profile_role = 'child'` (10+15 only); classification != '50_SECRETS' |
| 014_vault_rls_v1.sql:55 | `vault_documents_write` | vault_documents | FOR ALL | `app.profile_role = 'admin'` |

ENABLE ROW LEVEL SECURITY: `014_vault_rls_v1.sql:39`. FORCE ROW LEVEL SECURITY: `014_vault_rls_v1.sql:40`

> **Note:** schema.sql defines `vault_child_filter` using `jarvis.current_user`. Migration 014 introduces `vault_documents_read`/`vault_documents_write` using `app.profile_role`. Both policies may be simultaneously active unless 014 explicitly dropped `vault_child_filter` (it drops `vault_child_filter` via `DROP POLICY IF EXISTS`). Confirmed: line 35 of 014 drops it.

### `vault_pipeline`

| Migration | Policy Name | Table | Operation | GUC Checked |
|-----------|-------------|-------|-----------|-------------|
| 014_vault_rls_v1.sql:64 | `vault_pipeline_admin` | vault_pipeline | FOR ALL | `app.profile_role = 'admin'` |

ENABLE ROW LEVEL SECURITY + FORCE: `014_vault_rls_v1.sql:61–62`

### `vault_access_log`

| Migration | Policy Name | Table | Operation | GUC Checked |
|-----------|-------------|-------|-----------|-------------|
| 014_vault_rls_v1.sql:73 | `vault_access_log_admin` | vault_access_log | FOR ALL | `app.profile_role = 'admin'` |

ENABLE ROW LEVEL SECURITY + FORCE: `014_vault_rls_v1.sql:70–71`

---

## 4. Existing SECURITY DEFINER Functions

| Function | Migration | Owner / search_path | Purpose |
|----------|-----------|---------------------|---------|
| `sync_profile_to_user()` | 013_workspace_seeding.sql:38–74 | SECURITY DEFINER, `SET search_path = public` | Trigger on alpha_profiles (INSERT/UPDATE/DELETE) → mirrors rows to alpha_users. Bypasses RLS on alpha_users so trigger runs as table owner (jarvisbrain). |
| `rating_level(r TEXT)` | 009_child_profiles.sql:37–45 | Not SECURITY DEFINER; `LANGUAGE sql IMMUTABLE` | Returns integer severity for content rating strings. Used inside child_content_rating and child_memory_rating RLS policies. No owner override, no search_path set. |

**Trigger binding:**
- `trg_sync_profile_to_user` on `alpha_profiles` AFTER INSERT OR UPDATE OR DELETE calls `sync_profile_to_user()` (013_workspace_seeding.sql:80–85).

---

## 5. Database Roles

No `CREATE ROLE` statements appear in any migration file. The role `jarvis_alpha_app` is used throughout GRANTs but is never created by migrations — it is assumed to pre-exist (created outside migration files, likely in initial DB provisioning).

### GRANTs by table

| Table | Role | Privileges | Migration |
|-------|------|-----------|-----------|
| alpha_approval_queue | jarvis_alpha_app | SELECT, INSERT, UPDATE, DELETE | 010_approval_gateway.sql:72 |
| alpha_approval_audit | jarvis_alpha_app | SELECT, INSERT (DELETE/UPDATE explicitly revoked) | 010_approval_gateway.sql:56, 73 |
| alpha_overnight_approvals | jarvis_alpha_app | SELECT, INSERT, UPDATE | 010_approval_gateway.sql:74 |
| vault_documents | jarvis_alpha_app | SELECT, INSERT, UPDATE, DELETE | 014_vault_rls_v1.sql:78 |
| vault_pipeline | jarvis_alpha_app | SELECT, INSERT, UPDATE, DELETE | 014_vault_rls_v1.sql:79 |
| vault_access_log | jarvis_alpha_app | SELECT, INSERT, UPDATE, DELETE | 014_vault_rls_v1.sql:80 |
| vault_document_permissions | jarvis_alpha_app | SELECT, INSERT, UPDATE, DELETE | 014_vault_rls_v1.sql:81 |
| alpha_watchdog_events | jarvis_alpha_app | SELECT, INSERT | 012_watchdog_events.sql:55–56 |

### BYPASSRLS / NOBYPASSRLS

No migration sets `BYPASSRLS` or `NOBYPASSRLS` on any role. The `SET ROLE jarvis_alpha_app` call in `brain/db/rls.py:84` revokes BYPASSRLS for request-path connections (since `jarvis_alpha_app` is a non-superuser role). Background writers (`buddy_agent`, `watchdog_agent`, `executor`, `tasks/watchdog`) do **not** call `SET ROLE` — they connect as whatever role the DSN credential grants, which may have BYPASSRLS if the DSN user is the DB owner.

---

## 6. Other Background Writers

All `asyncpg.create_pool` / `asyncpg.connect` calls in `brain/` (excluding `brain/routes/`):

| File | Line | Call | Pool Size | DSN Source |
|------|------|------|-----------|-----------|
| brain/db/pool.py | 10 | `asyncpg.create_pool(dsn, min_size=2, max_size=10)` | 2–10 | `ALPHA_DB_DSN` env via `brain/core/config.py` |
| brain/tasks/executor.py | 406 | `asyncpg.create_pool(dsn, min_size=2, max_size=5)` | 2–5 | `get_secret("JARVIS_ALPHA_DB_DSN")` |
| brain/tasks/watchdog.py | 149 | `asyncpg.create_pool(dsn, min_size=1, max_size=2)` | 1–2 | `get_secret("JARVIS_ALPHA_DB_DSN")` |
| brain/agents/buddy_agent.py | 228 | `asyncpg.create_pool(dsn, min_size=1, max_size=3)` | 1–3 | `os.environ.get("ALPHA_DB_DSN")` |
| brain/agents/watchdog_agent.py | 359 | `asyncpg.create_pool(dsn, min_size=1, max_size=3)` | 1–3 | `os.environ["ALPHA_DB_DSN"]` |

**Summary of background writers (non-route):**

1. **`brain/db/pool.py`** — The FastAPI app's shared pool (not a background writer itself; used by routes via `rls_connection`).
2. **`brain/tasks/executor.py`** — TaskGraph executor. Creates its own pool. Writes to alpha_task_graphs, alpha_task_steps, alpha_task_events.
3. **`brain/tasks/watchdog.py`** — TaskGraph stuck-step watchdog. Creates its own pool. Writes to alpha_task_steps, alpha_task_graphs, alpha_task_events.
4. **`brain/agents/buddy_agent.py`** — Buddy agent. Creates its own pool. Writes to alpha_buddy_events, alpha_approval_queue (expiry), alpha_approval_audit, alpha_conversation_memory (bulk DELETEs).
5. **`brain/agents/watchdog_agent.py`** — Service health watchdog. Creates its own pool. Writes to alpha_watchdog_events.

**DSN name inconsistency:** buddy_agent and watchdog_agent use `ALPHA_DB_DSN`; executor and tasks/watchdog use `JARVIS_ALPHA_DB_DSN` (via secrets manager). These may resolve to the same DSN but are loaded differently.

---

## 7. Middleware RLS Setup — Request Lifecycle

### JWT auth flow (`brain/middleware/jwt_auth.py`)

`JWTAuthMiddleware.dispatch()` runs on every non-skipped request:

1. Validates `Authorization: Bearer <token>` header.
2. Decodes JWT (RS256, issuer-keyed public key from `~/jarvis/pki/services/` or `brain/pki/jwt_public.pem`).
3. Writes to `request.state`:
   - `request.state.user_id` ← `sub` claim
   - `request.state.role` ← `role` claim (default: `"user"`)
   - `request.state.max_rating` ← `max_rating` claim (default: `"all_ages"`)
   - `request.state.workspace_id` ← `workspace_id` claim
   - `request.state.profile_id` ← `profile_id` claim (fallback: sub)
   - `request.state.scopes`, `actor_type`, `display_name`, `iss`, `child_age`

This is pure Python — **no database calls in middleware**.

### GUC injection flow (`brain/db/rls.py`)

`rls_connection(request)` is called inside route handlers:

1. Reads `user_id`, `profile_role`, `max_rating`, `workspace_id` from `request.state`.
2. Calls `SET ROLE jarvis_alpha_app` on the connection (revokes BYPASSRLS).
3. Inside a transaction, sets 8 GUCs:

| GUC | Value set | Used by |
|-----|-----------|---------|
| `app.user_id` | JWT sub | (no policy found using this directly) |
| `app.profile_id` | JWT sub | child_thread_isolation, child_message_isolation |
| `app.profile_role` | `'admin'` or `'child'` | All child isolation + vault policies |
| `app.max_rating` | `'all_ages'`/`'age_8_plus'`/`'teen'`/`'adult'` | child_content_rating, child_memory_rating |
| `app.workspace_id` | JWT workspace_id claim | (no policy found using this directly) |
| `jarvis.current_user` | JWT sub | task_graphs, buddy_events, semantic_memory, memory.py reads |
| `jarvis.role` | `'platform_admin'` or `'user'` | task_graphs_isolation, task_steps_isolation, buddy_events_isolation |
| `rls.user_id` | JWT sub | chat_threads_isolation, chat_messages_isolation |

4. Yields the connection.
5. On exit: `RESET ROLE`.

**Where each GUC is NOT set by middleware:**
- `jarvis.is_admin` — referenced in semantic_isolation policy (003_memory_tiers.sql:37) but never set anywhere in application code. Set to NULL = treated as false by `= 'true'` check.
- `rls.user_id` for background writers — only watchdog_agent and watchdog route set it to `'system'`; buddy_agent never sets it.

---

## 8. Open Questions For Design

### OQ-1: `buddy_agent.py` bulk DELETEs bypass RLS entirely

**Location:** buddy_agent.py lines 139–175 (3 DELETE statements on `alpha_conversation_memory`)

`alpha_conversation_memory` has no `ENABLE ROW LEVEL SECURITY` in any migration, so DELETEs are currently unguarded regardless. But the docstring in `brain/db/rls.py:26` explicitly states: *"Background services (buddy, watchdog, executor) MUST NOT use this helper. They use SECURITY DEFINER functions instead — see step 7 of build order."* No SECURITY DEFINER functions for background memory writes exist yet — Step 7 is the planned build step. The bulk DELETEs on lines 139–175 predate that design decision.

### OQ-2: `alpha_conversation_memory` has no RLS enabled

No migration calls `ALTER TABLE alpha_conversation_memory ENABLE ROW LEVEL SECURITY`. The `alpha_memory_isolation` policy referenced in `brain/db/rls.py:47` comment ("used by alpha_memory_isolation (legacy convention)") does not appear in any migration. Memory.py sets `jarvis.current_user` per-connection, but those GUCs provide no actual row filtering until RLS is enabled and a policy exists.

### OQ-3: `watchdog_events_system_write` policy — GUC mismatch between agent and buddy

`alpha_watchdog_events` write policy requires `rls.user_id = 'system'` (012_watchdog_events.sql:53). `watchdog_agent.py:122` correctly sets `set_config('rls.user_id', 'system', true)` before its INSERT. However, `buddy_agent.py` also writes to `alpha_buddy_events` (a different table) but the `alpha_buddy_events` `buddy_events_isolation` policy (008_buddy_events.sql) checks `jarvis.current_user` and `jarvis.role`, neither of which are set in buddy_agent before those writes.

### OQ-4: `buddy_events_isolation` policy references `jarvis.role = 'admin'` but buddy_agent sets `jarvis.current_user`

`buddy_events_isolation` (008_buddy_events.sql:34–41) gates writes on `graph_id IN (SELECT id FROM alpha_task_graphs WHERE created_by = jarvis.current_user OR jarvis.role = 'admin')`. `buddy_agent.py:189` sets `jarvis.current_user` to the iterating `user_id` (not 'admin') on one connection, then fires INSERTs to `alpha_buddy_events` on separate connections (lines 115, 129, 178, 205) where `jarvis.current_user` is unset. Those separate-connection INSERTs will fail the RLS policy silently (RLS returns 0 rows filtered, INSERT blocked) unless `alpha_buddy_events` in production is the `005_buddy_events.sql` shape (which has no RLS).

### OQ-5: `task_events_isolation` policy admits only literal `'admin'` string

008b_task_events.sql:35: `USING (current_setting('jarvis.current_user', TRUE) = 'admin')`. This means only connections where `jarvis.current_user` is set to the string `'admin'` can see any task events. The executor sets `jarvis.current_user = 'admin'` (executor.py:46), so that path works. However, no user-facing route sets `jarvis.current_user = 'admin'` — `rls_connection()` sets it to the JWT sub claim (e.g. `'ken'`). Result: route handlers using `rls_connection` will see zero rows from `alpha_task_events`.

### OQ-6: `jarvis.role` value mismatch between `rls_connection` and executor

`rls_connection()` sets `jarvis.role = 'platform_admin'` for admin users. Task graph policies check `jarvis.role = 'admin'` (literal). These will not match. An admin user routing through `rls_connection` will fail the `OR current_setting('jarvis.role') = 'admin'` branch in `task_graphs_isolation` and `task_steps_isolation`. Access falls through to `created_by = jarvis.current_user` — which works only for graphs they created. Executor sets `jarvis.role = 'admin'` (exact match), so executor access works.

### OQ-7: `jarvis.is_admin` is written nowhere

`semantic_isolation` policy (003_memory_tiers.sql:37) has `OR current_setting('jarvis.is_admin', true) = 'true'`. No code in the codebase sets this GUC — the `true` flag in `current_setting()` means it returns NULL rather than raising an error when unset, so `NULL = 'true'` evaluates to false. The admin escape hatch in semantic_isolation is permanently inoperative.

### OQ-8: Two conflicting `alpha_buddy_events` table definitions

- `005_buddy_events.sql` — creates `alpha_buddy_events` with columns `(id, user_id, event_type, title, body, priority, read, created_at)`. No RLS.
- `008_buddy_events.sql` — creates `alpha_buddy_events` with columns `(id, event_type, graph_id, step_id, message, priority, read, created_at)` with RLS. Has `graph_id` FK to alpha_task_graphs.

These are incompatible schemas with the same table name. `buddy_agent.py` uses the `005` schema (inserts `user_id, event_type, title, body, priority`). `TaskGraphExecutor.notify()` in executor.py uses the `008` schema (inserts `event_type, graph_id, step_id, message, priority`). The active table shape depends on migration apply order and whether any `IF NOT EXISTS` guards prevented the `008` definition from replacing the `005` definition.

### OQ-9: `memory.py` sets `jarvis.current_user` inside a transaction but queries use parameterized `user_id`

`_get_semantic()`, `_get_episodic()`, `store()`, `save_semantic()`, `promote_to_semantic()` all set `jarvis.current_user = user_id` then query with `WHERE user_id = $1` (parameter). The GUC is redundant for these queries because they filter by parameter — but it is required to satisfy the `semantic_isolation` RLS policy (`user_id::text = current_setting('jarvis.current_user')`). If a future refactor removes the `set_config` call (viewing it as redundant), RLS will silently block all reads from `alpha_semantic_memory`.

### OQ-10: `DSN naming inconsistency` across background writers

- `buddy_agent.py` and `watchdog_agent.py` read `ALPHA_DB_DSN` directly from env.
- `tasks/executor.py` and `tasks/watchdog.py` read `JARVIS_ALPHA_DB_DSN` via secrets manager (`get_secret()`).
- `brain/app.py` uses `ALPHA_DB_DSN` from `brain/core/config.py`.

Two different env var names for potentially the same DSN. If the secrets manager returns a different credential than the env var (e.g., a different DB user with or without BYPASSRLS), the RLS behavior of the executor vs. buddy will differ silently.
