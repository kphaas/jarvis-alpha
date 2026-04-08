# STAGE3_DISCOVERY.md
## Background Writer RLS Audit — Step 6.5 Stage 3 Pre-work
**Date:** 2026-04-08  
**Author:** Claude Code (read-only audit, no modifications)  
**Scope:** Every write to RLS-governed tables outside `rls_connection()`

---

## Summary

| Task | One-line verdict |
|------|-----------------|
| 1 | 18 distinct write sites across 7 files; 14 are outside `rls_connection()` |
| 2 | 3 clean request-path callers; 4 background agents/scripts all dirty |
| 3 | `memory.py` has 5 write functions; `evict_working()` has ZERO GUCs; the rest set `jarvis.current_user` only — missing ROLE switch and `app.*`/`rls.*` |
| 4 | `buddy_agent.py` has 6 write blocks; zero set any GUC before writing |
| 5 | `approval_notifier.py` inserts to `alpha_buddy_events` with NO user_id and NO GUC — NULL user_id confirmed |
| 6 | `executor.py` sets `jarvis.current_user='admin'` + `jarvis.role='admin'` only — no ROLE switch, no `app.*`, no `rls.*` |
| 7 | `watchdog_agent.py` sets `rls.user_id='system'` only — missing ROLE switch, missing `jarvis.*` and `app.*` |
| 8 | `rls_connection()` is used only in `routes/` and `ingest/` — never in agents, services, or tasks |
| 9 | `rotate_service_token.py` writes to `alpha_buddy_events` via raw `psql` subprocess — completely outside app DB user and GUC system |

---

## Task 1 — Full Write Inventory

All `INSERT`/`UPDATE`/`DELETE` against `alpha_*` tables in `brain/` and `scripts/`.  
Excludes test files, `.venv`, `__pycache__`.

| # | File | Line | Table | Op | GUC State |
|---|------|------|-------|----|-----------|
| 1 | `brain/services/approval_notifier.py` | 147 | `alpha_buddy_events` | INSERT | NONE |
| 2 | `brain/agents/buddy_agent.py` | 37 | `alpha_buddy_events` | INSERT | NONE |
| 3 | `brain/agents/buddy_agent.py` | 53 | `alpha_approval_queue` | UPDATE | NONE |
| 4 | `brain/agents/buddy_agent.py` | 66 | `alpha_approval_audit` | INSERT | NONE |
| 5 | `brain/agents/buddy_agent.py` | 139 | `alpha_conversation_memory` | DELETE | NONE |
| 6 | `brain/agents/buddy_agent.py` | 150 | `alpha_conversation_memory` | DELETE | NONE |
| 7 | `brain/agents/buddy_agent.py` | 164 | `alpha_conversation_memory` | DELETE | NONE |
| 8 | `brain/memory/memory.py` | 207 | `alpha_conversation_memory` | UPDATE | `jarvis.current_user` only |
| 9 | `brain/memory/memory.py` | 264 | `alpha_conversation_memory` | INSERT | `jarvis.current_user` only |
| 10 | `brain/memory/memory.py` | 304 | `alpha_semantic_memory` | INSERT | `jarvis.current_user` only |
| 11 | `brain/memory/memory.py` | 352 | `alpha_semantic_memory` | INSERT | `jarvis.current_user` only |
| 12 | `brain/memory/memory.py` | 372 | `alpha_conversation_memory` | DELETE | NONE |
| 13 | `brain/agents/watchdog_agent.py` | 124 | `alpha_watchdog_events` | INSERT | `rls.user_id='system'` only |
| 14 | `brain/tasks/executor.py` | 184 | `alpha_task_graphs` | UPDATE | `jarvis.current_user='admin'`, `jarvis.role='admin'` — no ROLE switch |
| 15 | `brain/tasks/executor.py` | ~280–390 | `alpha_task_steps` | UPDATE (many) | same partial GUC |
| 16 | `brain/tasks/executor.py` | 495 | `alpha_task_events` | INSERT | same partial GUC |
| 17 | `brain/routes/approvals.py` | 183 | `alpha_approval_queue` | UPDATE | NONE — bare pool |
| 18 | `brain/routes/approvals.py` | 205 | `alpha_approval_audit` | INSERT | NONE — bare pool |
| S1 | `scripts/rotate_service_token.py` | 215 | `alpha_buddy_events` | INSERT | raw `psql` subprocess — OS peer auth |

**Note on `alpha_approval_queue` / `alpha_approval_audit`:** These tables were not in the original RLS-governed list passed to this audit, but they receive writes from both a background agent (`buddy_agent._expire_pending_approvals`) and a route (`approvals.py`) without any GUC. Flag for Ken to confirm RLS status.

---

## Task 2 — Classification

### REQUEST PATH (in `routes/` or `ingest/`, traceable to FastAPI)

| File | Tables Written | Via `rls_connection`? |
|------|---------------|----------------------|
| `brain/routes/chat.py` | `alpha_conversation_memory` (via `memory.store()`) | Partial — calls `memory.store()` which opens its own connection with `jarvis.current_user` only; no ROLE switch |
| `brain/routes/ask.py` | `alpha_conversation_memory` (via `memory.store()`) | Same as chat.py |
| `brain/routes/tasks.py` | `alpha_task_graphs`, `alpha_task_steps` | YES ✓ |
| `brain/routes/vault.py` | vault tables (not in RLS list) | YES ✓ |
| `brain/routes/dream.py` | dream tables (not in RLS list) | YES ✓ |
| `brain/ingest/excel.py` | vault tables | YES ✓ |
| `brain/ingest/pdf.py` | vault tables | YES ✓ |
| `brain/routes/approvals.py` | `alpha_approval_queue`, `alpha_approval_audit` | NO — bare `pool.acquire()` |

### BACKGROUND AGENT (runs outside FastAPI, as a LaunchAgent or loop)

| File | Tables Written | GUC State |
|------|---------------|-----------|
| `brain/agents/buddy_agent.py` | `alpha_buddy_events`, `alpha_approval_queue`, `alpha_approval_audit`, `alpha_conversation_memory` | NONE for direct writes; `jarvis.current_user` only for read + delete blocks |
| `brain/memory/memory.py` (called by buddy) | `alpha_conversation_memory`, `alpha_semantic_memory` | `jarvis.current_user` only; `evict_working()` has NO GUC |
| `brain/agents/watchdog_agent.py` | `alpha_watchdog_events` | `rls.user_id='system'` only |
| `brain/tasks/executor.py` (standalone) | `alpha_task_graphs`, `alpha_task_steps`, `alpha_task_events` | `jarvis.current_user='admin'`, `jarvis.role='admin'` — partial |

### BACKGROUND SCRIPT

| File | Tables Written | Method |
|------|---------------|--------|
| `scripts/rotate_service_token.py` | `alpha_buddy_events` | Raw `psql` subprocess as OS local user — no GUC, no app user |

### UNCLASSIFIED

| File | Notes |
|------|-------|
| `brain/tasks/executor.py` (in-process `TaskGraphExecutor` class) | Also exported for in-process use from FastAPI (routes/tasks.py instantiates it) — dual path: both request-path and standalone daemon |

---

## Task 3 — memory.py Deep Dive

**File:** `brain/memory/memory.py`  
**Class:** `MemoryService(pool: asyncpg.Pool)`

### Write Functions

| Function | Line | Table | Op | GUC Set | Called From |
|----------|------|-------|----|---------|-------------|
| `_get_episodic` | 207 | `alpha_conversation_memory` | UPDATE (access_count) | `jarvis.current_user` | REQUEST PATH: `build_context()` → `ask.py`, `chat.py` |
| `store` | 264 | `alpha_conversation_memory` | INSERT | `jarvis.current_user` | REQUEST PATH (`ask.py:152,160`, `chat.py:369`); also callable from background |
| `save_semantic` | 304 | `alpha_semantic_memory` | INSERT | `jarvis.current_user` | REQUEST PATH: `ask.py` (via `/v1/ask` route) |
| `promote_to_semantic` | 352 | `alpha_semantic_memory` | INSERT | `jarvis.current_user` | **BACKGROUND**: `buddy_agent.py:124` |
| `evict_working` | 372 | `alpha_conversation_memory` | DELETE | **NONE** | **BACKGROUND**: `buddy_agent.py:110` |

### GUC Assessment

All write functions open their **own connection** via `self.pool.acquire()` — they do NOT receive the `rls_connection()` connection from the caller. This means:

- **No `SET ROLE jarvis_alpha_app`** — runs as the pool's DB role (presumably `jarvisbrain` with BYPASSRLS or superuser)
- **Missing `app.*` GUCs** — `app.user_id`, `app.profile_id`, `app.profile_role`, `app.max_rating`, `app.workspace_id` never set
- **Missing `rls.*` GUC** — `rls.user_id` never set

The `jarvis.current_user` GUC is set, which satisfies the `alpha_memory_isolation` policy, but:

1. `evict_working()` has **zero** GUC setup — it deletes rows cross-user if `jarvisbrain` has BYPASSRLS
2. Even functions that set `jarvis.current_user` skip the ROLE switch, so if `jarvisbrain` has BYPASSRLS, the policies are ignored entirely

### Call Sites (`store`, `promote_to_semantic`, `evict_working`)

```
brain/routes/ask.py:152    memory.store(...)   ← request path
brain/routes/ask.py:160    memory.store(...)   ← request path
brain/routes/chat.py:369   memory.store(...)   ← request path (fire-and-forget task)
brain/agents/buddy_agent.py:110  memory.evict_working()    ← BACKGROUND
brain/agents/buddy_agent.py:124  memory.promote_to_semantic(user_uuid)  ← BACKGROUND
```

`save_semantic` is called from within request path routes (ask.py explicitly handles "remember this" intent).

### Flags

- `evict_working()` at line 372 has no GUC whatsoever — **highest risk** for cross-user data deletion if RLS is the only guard
- `store()` is called from chat.py line 369 inside an `asyncio.create_task()` — fire-and-forget — the background task has no access to the original request, so even if caller had rls_connection, the task cannot inherit it

---

## Task 4 — buddy_agent.py Deep Dive

**File:** `brain/agents/buddy_agent.py`  
**Entry point:** `run_buddy()` — standalone asyncio loop, own `asyncpg.create_pool(ALPHA_DB_DSN)`

### DB Write Operations

| Function | Line | Table | Op | GUC Before Write |
|----------|------|-------|----|-----------------|
| `_write_event` | 35–46 | `alpha_buddy_events` | INSERT | **NONE** |
| `_expire_pending_approvals` | 53 | `alpha_approval_queue` | UPDATE | **NONE** |
| `_expire_pending_approvals` | 66 | `alpha_approval_audit` | INSERT | **NONE** |
| `_run_cycle` (eviction event) | 115 | `alpha_buddy_events` | INSERT (via `_write_event`) | **NONE** |
| `_run_cycle` (promotion event) | 128 | `alpha_buddy_events` | INSERT (via `_write_event`) | **NONE** |
| `_run_cycle` (episodic eviction) | 139 | `alpha_conversation_memory` | DELETE | **NONE** |
| `_run_cycle` (episodic cap) | 150 | `alpha_conversation_memory` | DELETE | **NONE** |
| `_run_cycle` (semantic cap) | 164 | `alpha_conversation_memory` | DELETE | **NONE** |
| `_run_cycle` (aging alert) | 205 | `alpha_buddy_events` | INSERT (via `_write_event`) | `jarvis.current_user` SET (line 189) — but ONLY for the SELECT that precedes it, NOT on the same connection as the write |

**Key detail on line 187–212:** Buddy opens one connection, sets `jarvis.current_user` for a SELECT, then calls `_write_event` which opens a **new** connection — so the GUC does NOT carry over to the write.

### Cross-Reference With RLS Policies

- `alpha_buddy_events` — RLS-governed; `user_id` column is NULL in all buddy writes (see Task 5 for notifier; buddy_agent explicitly passes `user_id=None` or `user_id=user_id` as a string)
- `alpha_approval_queue` / `alpha_approval_audit` — not in original list; needs confirmation
- `alpha_conversation_memory` — RLS-governed; bulk DELETEs are cross-user (no WHERE user_id check on the cap/semantic enforcements — wait, lines 139 and 150 DO filter by `str(user_id)`, but line 164's semantic cap also filters by `str(user_id)`). So the DELETEs are user-scoped by WHERE clause but rely on BYPASSRLS to execute them.

### Architectural Note

Lines 164–175 delete from `alpha_conversation_memory WHERE tier='semantic'`. This is inconsistent with `promote_to_semantic()` which writes to `alpha_semantic_memory`. Either `alpha_conversation_memory` is intentionally multi-tier (working/episodic/semantic), or this cap enforcement targets the wrong table. Flag for Ken.

---

## Task 5 — approval_notifier.py Deep Dive

**File:** `brain/services/approval_notifier.py`  
**Called from:** middleware (approval gateway), not a route — background/middleware path

### Writes to `alpha_buddy_events` (line 147–154)

```python
await conn.execute(
    """INSERT INTO alpha_buddy_events
       (event_type, title, body, priority, source, payload)
       VALUES ('alert', $1, $2, $3, 'approval_gateway', $4)""",
    notif["title"],
    notif["body"],
    notif["priority"],
    json.dumps(notif["payload"]),
)
```

**user_id column:** NOT in the INSERT column list → **receives NULL** (database default). Confirmed.

**GUC state:** None. Uses `pool = get_pool(); async with pool.acquire() as conn:` — no `rls_connection()`, no GUC of any kind.

**Connection path:** `get_pool()` (the global FastAPI pool) — runs as whatever role `jarvisbrain` uses (presumably BYPASSRLS or superuser).

### Other RLS-Governed Writes

None. The notifier only writes to `alpha_buddy_events`.

---

## Task 6 — executor.py Deep Dive

**File:** `brain/tasks/executor.py`  
**Entry points:**  
1. Standalone daemon: `main()` — own `asyncpg.create_pool(JARVIS_ALPHA_DB_DSN)`
2. In-process class: `TaskGraphExecutor` — initialized with the FastAPI pool from `routes/tasks.py`

### GUC Setup

Both paths use `_bind_executor_rls()` / `_bind_worker_rls()`:

```python
async def _bind_executor_rls(conn):
    await conn.execute("SELECT set_config('jarvis.current_user', 'admin', true)")
    await conn.execute("SELECT set_config('jarvis.role', 'admin', true)")
```

**What is set:** `jarvis.current_user='admin'`, `jarvis.role='admin'`  
**What is missing:** `SET ROLE jarvis_alpha_app`, `app.*` GUCs, `rls.*` GUC

### Write Operations

| Function | Table | Op | GUC State |
|----------|-------|----|-----------|
| `run_graph` (standalone) | `alpha_task_graphs` | UPDATE status | `jarvis.*` only |
| `run_graph` (standalone) | `alpha_task_steps` | UPDATE status/output/error (many) | `jarvis.*` only |
| `TaskGraphExecutor.notify` | `alpha_task_events` | INSERT | `jarvis.*` only |
| `TaskGraphExecutor.execute_step` | `alpha_task_steps` | UPDATE (running, complete, retrying, halted) | `jarvis.*` only |
| `TaskGraphExecutor.run_graph` | `alpha_task_graphs` | UPDATE (running, complete, halted) | `jarvis.*` only |
| `recover_stuck_graphs` | `alpha_task_graphs` | UPDATE status='pending' | `jarvis.*` only |

### Request Path vs Background

- **Standalone daemon** (`if __name__ == '__main__'`): pure background — own pool, `JARVIS_ALPHA_DB_DSN`
- **`TaskGraphExecutor` class**: dual path — instantiated by `routes/tasks.py` at startup; writes happen in background tasks spawned by `asyncio.create_task()` from within request handlers. The class uses the same FastAPI pool but binds its own GUCs (not rls_connection GUCs).

The routes in `routes/tasks.py` correctly use `rls_connection()` for their own writes (graph creation, step queuing) but the executor class's async tasks run independently with only `jarvis.*` GUCs.

---

## Task 7 — watchdog_agent.py Deep Dive

**File:** `brain/agents/watchdog_agent.py`  
**Entry point:** `main()` — standalone asyncio loop, own `asyncpg.create_pool(ALPHA_DB_DSN)`

### GUC Setup (`_log_event`, line 119–155)

```python
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("SELECT set_config('rls.user_id', 'system', true)")
        await conn.execute("""INSERT INTO alpha_watchdog_events ...""")
```

**What is set:** `rls.user_id='system'`  
**What is missing:** `SET ROLE jarvis_alpha_app`, `jarvis.*` GUCs, `app.*` GUCs

**Verdict:** Discovery report (STEP7_DISCOVERY.md) that said watchdog sets `rls.user_id = 'system'` is **CONFIRMED**. It is the only writer that sets any GUC at all, but it still does not do the ROLE switch.

### Write Operations

| Function | Table | Event Types |
|----------|-------|-------------|
| `_log_event` | `alpha_watchdog_events` | `restored`, `down`, `restart_triggered`, `restart_succeeded`, `restart_failed`, `degraded` |

No other RLS-governed tables are written. The `_load_services` function reads from `alpha_node_registry` (SELECT only).

---

## Task 8 — rls_connection() Usage Inventory

**File:** `brain/db/rls.py:42`

### Importers and Callers

| File | Import | Call Sites |
|------|--------|-----------|
| `brain/routes/vault.py` | ✓ | Lines 54, 104, 133, 185, 214 |
| `brain/routes/chat.py` | ✓ | Lines 85, 139, 181, 386, 401, 417, 431, 450 |
| `brain/routes/dream.py` | ✓ | Lines 105, 115 |
| `brain/routes/ask.py` | ✓ | Lines 68, 96 |
| `brain/routes/tasks.py` | ✓ | Lines 54, 78, 112, 166, 195, 226, 265, 346, 420, 450, 482, 509 |
| `brain/ingest/excel.py` | ✓ | Line 105 |
| `brain/ingest/pdf.py` | ✓ | Line 94 |

### NOT Using rls_connection

| File | Reason | Risk |
|------|--------|------|
| `brain/routes/approvals.py` | Uses bare `pool.acquire()` directly | Writes to `alpha_approval_queue`/`alpha_approval_audit` without GUC |
| `brain/agents/buddy_agent.py` | Background — own pool | Correct design but needs SECURITY DEFINER |
| `brain/agents/watchdog_agent.py` | Background — own pool | Correct design but needs SECURITY DEFINER |
| `brain/tasks/executor.py` | Background — own pool; in-process class uses FastAPI pool | Correct design but needs SECURITY DEFINER |
| `brain/services/approval_notifier.py` | Service — uses global FastAPI pool | Should use SECURITY DEFINER |
| `brain/memory/memory.py` | Opened from MemoryService with pool | Bypasses rls_connection even when called from request path |

**rls.py docstring** explicitly says: *"Background services (buddy, watchdog, executor) MUST NOT use this helper. They use SECURITY DEFINER functions instead — see step 7 of build order."* — This is already documented as the intended design. Stage 3 is implementing it.

---

## Task 9 — Scripts Audit

### Scripts that connect to PostgreSQL

| Script | Method | Tables Touched | Role/User | GUC |
|--------|--------|---------------|-----------|-----|
| `scripts/rotate_service_token.py` | Raw `psql` subprocess (`PSQL_BIN` + `-d jarvis_alpha`) | `alpha_buddy_events` (INSERT in `alert_failure`, SELECT in `verify_brain`) | OS local peer auth (runs as `jarvisbrain` or whatever OS user runs the script) | NONE |
| `scripts/apply_migrations.sh` | `psql -d $DB` | `schema_migrations` (DML) | Not specified (local peer) | NONE |
| `scripts/smoke_writer_role.sh` | `psql -h localhost -U jarvis_alpha_writer` | `alpha_conversation_memory` (SELECT only, for verification) | `jarvis_alpha_writer` | N/A (read-only) |
| `scripts/set_writer_password.sh` | `psql` (ALTER ROLE) | No tables | superuser/peer | N/A |

### Key Finding — rotate_service_token.py

Line 215–217: Builds a raw SQL string with `json.dumps(...).replace("'", "''")` and passes it to `subprocess.run([psql ...])`. This is:
1. Writing to `alpha_buddy_events` completely outside the application's GUC system
2. Bypasses RLS because `psql` connects as the local OS user (peer auth, likely `jarvisbrain` with BYPASSRLS)
3. **Potential SQL injection risk**: the `escaped` variable only escapes single quotes. If `payload_obj` contains characters that survive `replace("'", "''")`, this could be exploited. Recommend parameterized insert via Python `asyncpg` instead.

### Scripts That Do NOT Touch PostgreSQL

`power_sampler.py`, `gen_service_token.py`, `gen_test_token.py`, `service_identity.py`, all `.sh` start/restart/renew scripts — confirmed no direct DB writes to RLS-governed tables.

---

## Stage 3 Scope Recommendation

### MUST be wrapped in SECURITY DEFINER in Stage 3

These are background writers with no GUC or partial GUC that write to confirmed RLS-governed tables:

| Writer | Function Needed | Tables | Priority |
|--------|----------------|--------|----------|
| `buddy_agent._write_event` | `record_buddy_event(event_type, title, body, priority, user_id, source)` | `alpha_buddy_events` | P0 — called 5+ times per cycle |
| `memory.evict_working` | `evict_expired_working_memory()` | `alpha_conversation_memory` | P0 — no GUC at all |
| `memory.promote_to_semantic` | `promote_episodic_to_semantic(user_id)` | `alpha_semantic_memory`, `alpha_conversation_memory` | P0 — Stage 3 explicitly planned |
| `approval_notifier.send_approval_notification` | reuse `record_buddy_event` or dedicated `record_alert_event` | `alpha_buddy_events` | P0 — NULL user_id write |
| `buddy_agent._run_cycle` DELETEs (lines 139, 150, 164) | `evict_episodic_memory(user_id)` + `cap_episodic_memory(user_id)` | `alpha_conversation_memory` | P0 — three raw DELETEs, no GUC |

### Should be addressed in Stage 3 or Stage 4

| Writer | Issue | Recommendation |
|--------|-------|----------------|
| `watchdog_agent._log_event` | Sets `rls.user_id='system'` but no ROLE switch | SECURITY DEFINER `record_watchdog_event(...)` — `alpha_watchdog_events` has simpler policy but defense-in-depth applies |
| `executor._bind_executor_rls` | Sets `jarvis.*` only, no ROLE switch, no `app.*` | SECURITY DEFINER for all task graph/step mutations; or grant executor role explicit policy bypass |
| `routes/approvals.py` | Request path but uses bare `pool.acquire()` | Switch to `rls_connection()` since it's a route with JWT auth, OR create `record_approval_decision(queue_id, decision, actor_sub)` SECURITY DEFINER |

### Already clean — no action needed

| Writer | Why Clean |
|--------|-----------|
| `brain/routes/tasks.py` | All writes via `rls_connection()` ✓ |
| `brain/routes/chat.py` (direct writes) | All route-level writes via `rls_connection()` ✓ |
| `brain/routes/ask.py` (direct writes) | All route-level writes via `rls_connection()` ✓ |
| `brain/routes/vault.py` | All writes via `rls_connection()` ✓ |
| `brain/routes/dream.py` | All writes via `rls_connection()` ✓ |
| `brain/ingest/excel.py` | Via `rls_connection()` ✓ |
| `brain/ingest/pdf.py` | Via `rls_connection()` ✓ |

### Surprise Writers Ken Likely Didn't Know About

1. **`memory.store()` called from `chat.py:369` via `asyncio.create_task()`** — fire-and-forget task spawned inside a request handler. The task runs without the request context, so even if the route used `rls_connection()`, the spawned task cannot inherit it. The task calls `memory.store()` which opens its own connection with only `jarvis.current_user`. This means chat memory writes are partially outside RLS even on the request path.

2. **`routes/approvals.py` uses bare `pool.acquire()`** — This is a request-path route with JWT auth that writes to `alpha_approval_queue` and `alpha_approval_audit` without using `rls_connection()` or any GUC. Not a background writer but still unprotected.

3. **`buddy_agent` has THREE separate DELETE blocks on `alpha_conversation_memory`** (lines 139, 150, 164) — beyond the `evict_working()` call at line 110 which was already known. Total of 4 write paths to `alpha_conversation_memory` from buddy, not 1.

4. **`rotate_service_token.py` writes via raw `psql`** — completely invisible to the application's connection pool and GUC system. Also has a SQL injection surface.

5. **`alpha_approval_queue` and `alpha_approval_audit`** are written by `buddy_agent._expire_pending_approvals` with zero GUC. If these tables have RLS, expiry is currently bypassed by BYPASSRLS on the DB role.

6. **`memory_manager.py` is a stub** — All methods are `pass`. Despite being imported in `thread_manager.py`, it does no actual DB work. Not a risk, but confirms that `MemoryService` (brain/memory/memory.py) is the real implementation.

---

## Open Questions for Ken Before Coding Starts

1. **Does `jarvisbrain` DB role have BYPASSRLS?** If yes, ALL background writes work today (policies are silently skipped). Stage 3 would be defense-in-depth / preparation for dropping BYPASSRLS from `jarvisbrain`. If no, some background paths are already broken.

2. **What DB role do buddy/watchdog/executor connect as?** All three use `ALPHA_DB_DSN` / `JARVIS_ALPHA_DB_DSN` from env/secrets. Is this the `jarvisbrain` role, `jarvis_alpha_writer`, or something else?

3. **Is `alpha_approval_queue` RLS-governed?** It's not in the original list but `buddy_agent` writes to it without any GUC. If it has RLS, approval expiry is broken today.

4. **Is `alpha_approval_audit` RLS-governed?** Same question — buddy writes to it on expiry with zero GUC.

5. **Intended design for `alpha_conversation_memory tier='semantic'`?** `buddy_agent` line 164 deletes from `alpha_conversation_memory WHERE tier='semantic'` but `promote_to_semantic()` writes to `alpha_semantic_memory`. Are both tables used for semantic-tier content, or is the buddy cap enforcement targeting the wrong table?

6. **Should `approval_notifier.py` be wrapped in Stage 3?** It's a service (not strictly background agent) called from middleware. Simplest fix: add `user_id` to the INSERT and wrap in SECURITY DEFINER alongside `record_buddy_event`. Or: fix it to use `rls_connection()` if it always runs in a request context (check call sites in middleware).

7. **`memory.store()` called via `asyncio.create_task()` in `chat.py:369`** — The fire-and-forget pattern means the task runs outside the request lifecycle. Should this become a queue-based write (write to a staging table, flush via buddy cycle) or should `store()` be wrapped in a SECURITY DEFINER that accepts explicit user_id?

8. **Stage 3 function signatures**: The three planned SECURITY DEFINER functions (`record_buddy_event`, `evict_expired_working_memory`, `promote_episodic_to_semantic`) will need to cover at minimum 5 distinct write patterns from buddy alone. Should Stage 3 also add `evict_episodic_memory(user_id)`, `cap_episodic_memory(user_id)`, and `cap_semantic_memory(user_id)` as separate functions, or batch them into one `run_buddy_maintenance(user_id)` function?

9. **`rotate_service_token.py` SQL injection**: The `alert_failure` function builds a raw SQL string with only `replace("'", "''")` escaping. Should this be migrated to Python `asyncpg` with parameterized queries as part of Stage 3, or tracked separately?

10. **`routes/approvals.py` missing `rls_connection()`**: Is this intentional (approval routes bypass RLS by design because they operate on queue items tied to the queue_id, not user_id)? Or is it an oversight?
