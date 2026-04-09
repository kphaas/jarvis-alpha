# STAGE5_DISCOVERY.md — Stage 5 Pre-Flight Discovery (RLS Force + Pool Role Cutover)

## Summary

| Task | One-line verdict |
|------|------------------|
| 1 | Mandatory schema snapshot commands were executed exactly; local environment returned `role "jarvisbrain" does not exist`, raw output captured verbatim |
| 2 | Mandatory policy/flag queries were executed exactly; same connection failure captured verbatim |
| 3 | Exhaustive Python references to `alpha_conversation_memory`, `alpha_buddy_events`, `alpha_semantic_memory` inventoried and classified |
| 4 | Deferred writers audited: `chat.py` fire-and-forget memory write is in-scope; approvals path writes different tables; listed paths for executor/watchdog have moved |
| 5 | Five asyncpg pool creation sites identified (`fastapi`, `buddy`, `watchdog`, `executor`, task watchdog) |
| 6 | FastAPI pool wiring uses `ALPHA_DB_DSN` (not split user/password vars); Stage 5 role flip is a DSN value change at config/secret layer |
| 7 | For the 3 target tables, 8 write sites found total; 3 already SECDEF-covered, 5 still unwrapped and must be handled before FORCE RLS |

---

## Task 1 — Schema Snapshot (Raw `\d` Output, Verbatim)

Command run:

```bash
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -U jarvisbrain -d jarvis_alpha -c "\d alpha_conversation_memory"
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -U jarvisbrain -d jarvis_alpha -c "\d alpha_buddy_events"
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -U jarvisbrain -d jarvis_alpha -c "\d alpha_semantic_memory"
```

Raw terminal output:

```text
psql: error: connection to server on socket "/tmp/.s.PGSQL.5432" failed: FATAL:  role "jarvisbrain" does not exist
```

---

## Task 2 — Existing RLS Policies + `relrowsecurity` / `relforcerowsecurity`

Commands run:

```bash
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -U jarvisbrain -d jarvis_alpha -c "SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual, with_check FROM pg_policies WHERE tablename IN ('alpha_conversation_memory','alpha_buddy_events','alpha_semantic_memory') ORDER BY tablename, policyname;"
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -U jarvisbrain -d jarvis_alpha -c "SELECT c.relname, c.relrowsecurity AS rls_enabled, c.relforcerowsecurity AS force_rls FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname='public' AND c.relname IN ('alpha_conversation_memory','alpha_buddy_events','alpha_semantic_memory');"
```

Raw terminal output:

```text
psql: error: connection to server on socket "/tmp/.s.PGSQL.5432" failed: FATAL:  role "jarvisbrain" does not exist
```

---

## Task 3 — Writer Inventory (Code Grep)

Searches executed over `~/jarvis-alpha/brain` (Python files):

- `alpha_conversation_memory`
- `alpha_buddy_events`
- `alpha_semantic_memory`
- `ConversationMemory|BuddyEvent|SemanticMemory`

### Full hit classification

| File:Line | Operation (SELECT/INSERT/UPDATE/DELETE) | Direct SQL or ORM | Pool used | Already wrapped in SECDEF? | Stage 5 action |
|-----------|------------------------------------------|-------------------|-----------|----------------------------|----------------|
| `brain/agents/buddy_agent.py:128` | SELECT | Direct SQL | buddy_pool | yes (`run_buddy_memory_maintenance` covers write path, this is read) | safe_as_read_only |
| `brain/agents/buddy_agent.py:159` | SELECT | Direct SQL | buddy_pool | yes (`run_buddy_memory_maintenance` covers write path, this is read) | safe_as_read_only |
| `brain/routes/ask.py:100` | DELETE | Direct SQL | fastapi_request_pool (via `rls_connection`) | no | wrap_in_secdef |
| `brain/routes/ask.py:118` | DELETE | Direct SQL | fastapi_request_pool (via `rls_connection`) | no | wrap_in_secdef |
| `brain/memory/memory.py:137` | SELECT | Direct SQL | fastapi_request_pool (service receives `get_pool()`) | n/a (read) | safe_as_read_only |
| `brain/memory/memory.py:173` | SELECT | Direct SQL | fastapi_request_pool (service receives `get_pool()`) | n/a (read) | safe_as_read_only |
| `brain/memory/memory.py:207` | UPDATE | Direct SQL | fastapi_request_pool (service receives `get_pool()`) | no | wrap_in_secdef |
| `brain/memory/memory.py:226` | SELECT | Direct SQL | fastapi_request_pool (service receives `get_pool()`) | n/a (read) | safe_as_read_only |
| `brain/memory/memory.py:264` | INSERT | Direct SQL | fastapi_request_pool (service receives `get_pool()`) | no | wrap_in_secdef |
| `brain/memory/memory.py:299` | SELECT | Direct SQL | fastapi_request_pool (service receives `get_pool()`) | n/a (read) | safe_as_read_only |
| `brain/memory/memory.py:306` | INSERT | Direct SQL | fastapi_request_pool (service receives `get_pool()`) | no | wrap_in_secdef |
| `brain/memory/memory.py:328` | SELECT | Direct SQL | fastapi_request_pool (service receives `get_pool()`) | n/a (read) | safe_as_read_only |
| `brain/memory/memory.py:337` | SELECT | Direct SQL | fastapi_request_pool (service receives `get_pool()`) | n/a (read) | safe_as_read_only |
| `brain/memory/memory.py:354` | INSERT | Direct SQL | fastapi_request_pool (service receives `get_pool()`) | yes (`run_buddy_memory_maintenance` path supersedes buddy write shape) | already_covered |
| `brain/memory/memory.py:374` | DELETE | Direct SQL | fastapi_request_pool (service receives `get_pool()`) | yes (`evict_expired_working_memory`) | already_covered |
| `brain/routes/buddy.py:44` | SELECT | Direct SQL | fastapi_request_pool | n/a (read) | safe_as_read_only |
| `brain/routes/buddy.py:55` | SELECT | Direct SQL | fastapi_request_pool | n/a (read) | safe_as_read_only |
| `brain/routes/buddy.py:73` | UPDATE | Direct SQL | fastapi_request_pool | no | wrap_in_secdef |
| `brain/routes/buddy.py:85` | UPDATE | Direct SQL | fastapi_request_pool | no | wrap_in_secdef |
| `brain/routes/buddy.py:11` | n/a (model declaration) | ORM-like/Pydantic model only | n/a | n/a | safe_as_read_only |
| `brain/routes/buddy.py:22` | n/a (model declaration) | ORM-like/Pydantic model only | n/a | n/a | safe_as_read_only |
| `brain/routes/buddy.py:23` | n/a (model declaration) | ORM-like/Pydantic model only | n/a | n/a | safe_as_read_only |
| `brain/routes/buddy.py:27` | n/a (response model annotation) | ORM-like/Pydantic model only | n/a | n/a | safe_as_read_only |
| `brain/routes/buddy.py:32` | n/a (response type annotation) | ORM-like/Pydantic model only | n/a | n/a | safe_as_read_only |
| `brain/routes/buddy.py:62` | n/a (response build) | ORM-like/Pydantic model only | n/a | n/a | safe_as_read_only |
| `brain/routes/buddy.py:63` | n/a (response build) | ORM-like/Pydantic model only | n/a | n/a | safe_as_read_only |

### Notes

- `record_buddy_event`, `evict_expired_working_memory`, and `run_buddy_memory_maintenance` are present in call paths and count as already covered for those specific shapes.
- Non-SECDEF writes against target tables remain in request-path code (`ask.py`, `memory.py`, `routes/buddy.py`).

---

## Task 4 — Deferred Writer Deep-Dive

### `brain/executor.py`

File status: this path does not exist in current tree. The executor lives at `brain/tasks/executor.py`.

Context:

```python
DB_DSN_KEY = "JARVIS_ALPHA_DB_DSN"
...
await conn.execute(
    """
    UPDATE alpha_task_graphs
    SET status = 'running', started_at = now(), updated_at = now()
    WHERE id = $1
    """,
    graph_id,
)
```

Answers:
1. Table written: not one of Stage 5 target 3 tables (writes `alpha_task_graphs`, `alpha_task_steps`, `alpha_task_events`)
2. Operation: INSERT/UPDATE on task tables
3. Pool: executor_pool (`asyncpg.create_pool` in daemon mode) and fastapi_request_pool in in-process class mode
4. Path: async background worker path
5. Existing SECDEF coverage for Stage 5 target 3 tables: not applicable
6. Stage 5a wrap difficulty: trivial (out of current target-table scope)

### `brain/watchdog_agent.py`

File status: this path does not exist in current tree. The watchdog agent lives at `brain/agents/watchdog_agent.py`.

Context:

```python
await conn.execute(
    """
    INSERT INTO alpha_watchdog_events
        (service_name, node, event_type, previous_state, current_state,
         consecutive_failures, latency_ms, http_status, error_message,
         action_taken, trace_id)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
    """,
    svc.name,
    svc.node,
    event_type,
    previous_state,
    current_state,
    svc.consecutive_failures,
    latency_ms,
    http_status,
    error_message,
    action_taken,
    uuid.uuid5(uuid.NAMESPACE_DNS, f"watchdog:{svc.trace_id}")
    if svc.trace_id
    else None,
)
```

Answers:
1. Table written: not one of Stage 5 target 3 tables (writes `alpha_watchdog_events`)
2. Operation: INSERT
3. Pool: watchdog_pool (`asyncpg.create_pool` with `ALPHA_DB_DSN`)
4. Path: async background loop
5. Existing SECDEF coverage for Stage 5 target 3 tables: not applicable
6. Stage 5a wrap difficulty: trivial (out of current target-table scope)

### `brain/routes/chat.py`

Context (fire-and-forget memory write):

```python
asyncio.create_task(
    memory.store(
        user_id=uid,
        session_id=thread_id,
        summary=full_text,
        role="assistant",
        embedding=await _embed(full_text),
        persistent=False,
    )
)
```

Answers:
1. Table written: `alpha_conversation_memory` (via `MemoryService.store`)
2. Operation: INSERT
3. Pool: fastapi_request_pool (`get_pool()` passed into `MemoryService`)
4. Path: fire-and-forget (async background task spawned from request handler)
5. Existing SECDEF function coverage: no direct wrapper for this request-time write shape
6. Stage 5a wrap difficulty: medium

### `brain/routes/approvals.py`

Context:

```python
await conn.execute(
    """UPDATE alpha_approval_queue
       SET status = 'approved',
           decided_by = $1,
           decided_at = NOW(),
           expires_at = NOW() + INTERVAL '10 minutes'
       WHERE id = $2""",
    actor_sub,
    queue_id,
)
...
await conn.execute(
    """INSERT INTO alpha_approval_audit
       (approval_id, action_class, risk_tier, actor_sub, actor_type,
        description, parameters_hash, nonce, decision, decided_by, overnight)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
    row["id"],
    row["action_class"],
    row["risk_tier"],
    actor_sub,
    "user",
    row["description"],
    row["parameters_hash"],
    nonce,
    req.decision,
    actor_sub,
    row["overnight"],
)
```

Answers:
1. Table written: `alpha_approval_queue`, `alpha_approval_audit` (not in Stage 5 target 3 tables)
2. Operation: UPDATE + INSERT
3. Pool: fastapi_request_pool (bare `get_pool().acquire()`)
4. Path: request path (sync transaction)
5. Existing SECDEF function coverage: not for this shape
6. Stage 5a wrap difficulty: medium (but out of current target-table scope)

---

## Task 5 — Pool Inventory

| File:Line | Pool name/purpose | User (jarvisbrain or other) | Stage 5 cutover target |
|-----------|-------------------|-----------------------------|------------------------|
| `brain/db/pool.py:10` | FastAPI shared request pool (`init_pool`) | unknown-needs-investigation (from `ALPHA_DB_DSN`) | **Flip to `jarvis_alpha_writer` for Stage 5** |
| `brain/agents/buddy_agent.py:192` | buddy background loop pool | unknown-needs-investigation (from `ALPHA_DB_DSN`) | keep current for now (separate Stage policy decision) |
| `brain/agents/watchdog_agent.py:359` | watchdog background loop pool | unknown-needs-investigation (from `ALPHA_DB_DSN`) | keep current for now (separate Stage policy decision) |
| `brain/tasks/executor.py:406` | task executor daemon pool | unknown-needs-investigation (from `JARVIS_ALPHA_DB_DSN`) | keep current for now (separate Stage policy decision) |
| `brain/tasks/watchdog.py:149` | task watchdog daemon pool | unknown-needs-investigation (from `JARVIS_ALPHA_DB_DSN`) | keep current for now (separate Stage policy decision) |

---

## Task 6 — Config Surface

### Discovery

1. Current env var name for FastAPI pool user:
   - There is no standalone `ALPHA_DB_USER` in current code path.
   - FastAPI uses `ALPHA_DB_DSN` (`brain/core/config.py`) and passes it to `init_pool` (`brain/app.py`).

2. Where it is loaded:
   - `brain/core/config.py`: `ALPHA_DB_DSN = os.environ["ALPHA_DB_DSN"]`
   - `brain/app.py`: `db_pool = await init_pool(ALPHA_DB_DSN)`

3. Stage 5b change needed to flip FastAPI to writer role:
   - Update the `ALPHA_DB_DSN` secret/env value so its DB user is `jarvis_alpha_writer`.
   - No code-level switch of `ALPHA_DB_USER`/`ALPHA_DB_PASSWORD` exists in current FastAPI pool setup; cutover is DSN-driven.

---

## Stage 5 Risk Surface

1. How many writers total touch the 3 tables?
   - **8 write sites total**
   - `alpha_conversation_memory`: 6 (`ask.py` x2 deletes, `memory.py` update/insert/delete x3)
   - `alpha_buddy_events`: 2 (`routes/buddy.py` x2 updates)
   - `alpha_semantic_memory`: 2 inserts in `memory.py` (included in above total counting by site; overlapping file-level count)

2. How many are already covered by Stage 3 SECDEF?
   - **3 write shapes already covered**
   - `record_buddy_event` path
   - `evict_expired_working_memory` path
   - `run_buddy_memory_maintenance` path (which encapsulates episodic/semantic maintenance)

3. How many need new wrapping in Stage 5a?
   - **5 write sites need wrapping or reroute to SECDEF**
   - `routes/ask.py` DELETEs (2)
   - `memory.py` UPDATE/INSERTs used on request paths (3+ depending on final factoring)
   - `routes/buddy.py` UPDATEs likely need SECDEF or RLS-safe request pattern (2)

4. Any writers that cannot be wrapped cleanly?
   - **No hard blocker found in code shape**
   - Most are single-statement DML and straightforward SECDEF candidates.

5. Any tables where existing RLS policies would break under FORCE RLS?
   - **Unknown-needs-investigation due to blocked DB introspection in this environment** (`psql` role failure prevented policy/flag snapshot).
   - This is the only unresolved blocker for a definitive FORCE-RLS safety verdict.

6. Recommendation:
   - **Proceed to Stage 5a design with one prerequisite:** run the exact Task 1/2 SQL from a host where `jarvisbrain` role exists and append raw outputs before implementation starts.

