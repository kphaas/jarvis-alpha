# TD-46 Phase 1 Discovery: Buddy Priority Column Type Mismatch

**Investigator:** Sandbox Claude  
**Date:** 2026-04-10  
**Status:** Phase 1 Complete — read-only investigation

---

## 1. Every Priority Reference in Buddy + Memory Code

### brain/agents/buddy_agent.py

**Lines 30-42 — `_normalize_buddy_priority` (read/normalize)**
```python
def _normalize_buddy_priority(priority: int | str | None) -> int:
    if priority is None:
        return 2
    if isinstance(priority, int):
        return priority
    p = str(priority).strip().lower()
    if p in ("info", "low"):
        return 1
    if p in ("normal", "medium", ""):
        return 2
    if p in ("high", "alert", "critical", "warn", "warning"):
        return 3
    return 2
```

**Lines 45-73 — `_write_event` (write via SECDEF)**
```python
async def _write_event(
    pool: asyncpg.Pool,
    *,
    user_id: str | None,
    event_type: str,
    title: str,
    body: str = "",
    priority: int | str | None = 2,
    source: str = "buddy_agent",
    payload: dict | list | str | None = None,
) -> uuid.UUID:
    payload_json = "{}" if payload is None else payload
    if not isinstance(payload_json, str):
        payload_json = json.dumps(payload_json)

    p_priority = _normalize_buddy_priority(priority)
    p_event_type = _normalize_buddy_event_type(event_type)

    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT public.record_buddy_event($1, $2, $3, $4, $5, $6, $7)",
            user_id if user_id else "system",
            p_event_type,
            title,
            body,
            p_priority,
            source,
            payload_json,
        )
```

**Line 117 — write, priority=2 (expired approvals event)**  
**Line 149 — write, priority=1 (maintenance complete event)**  
**Line 166 — write, priority=3 (aging memories alert)**

### brain/services/approval_notifier.py

**Lines 19-31 — `_notif_priority_int` (read/normalize):** Same pattern as buddy, converts priority to int 1/2/3.  
**Lines 163-171 — write:** Calls `record_buddy_event` SECDEF with normalized integer priority.

### brain/tasks/watchdog.py

**Lines 108-121 — write (SEPARATE BUG):**
```python
await conn.execute("""
    INSERT INTO alpha_task_events (
        event_type, graph_id, step_id, message, priority
    )
    VALUES ($1, $2, $3, $4, $5)
""", evt_type, row["graph_id"], step_id, detail, pri)
```
`pri` is set to `"high"` (line 72) or `"critical"` (line 98) — TEXT values. See Section 2 for why this is a separate bug.

### brain/tasks/executor.py

**Lines 483-507 — write (SAME SEPARATE BUG):**
```python
async def notify(self, event_type, graph_id, step_id=None, message="", priority="normal"):
    ...
    INSERT INTO alpha_task_events (event_type, graph_id, step_id, message, priority)
    VALUES ($1, $2::uuid, $3, $4, $5)
```

### brain/db/migrations/005_buddy_events.sql

**Line 9 — schema definition:**
```sql
priority   INT NOT NULL DEFAULT 2,
```

### brain/db/migrations/008b_task_events.sql

**Lines 20-21 — schema definition (original):**
```sql
priority    TEXT NOT NULL DEFAULT 'normal'
    CHECK (priority IN ('low', 'normal', 'high', 'critical')),
```

### brain/db/migrations/20260408_130000_security_definer_functions.sql

**Line 15 — SECDEF parameter (THE BUG):**
```sql
p_priority TEXT,
```

### brain/db/migrations/20260408_140000_record_buddy_event_fix.sql

**Line 12 — SECDEF parameter (THE FIX):**
```sql
p_priority INTEGER,
```

---

## 2. Schema Reality

### alpha_buddy_events (live \d output)

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
Check constraints:
    "alpha_buddy_events_event_type_check" CHECK (event_type = ANY (ARRAY['alert','reminder','suggestion','system']))
```

### alpha_conversation_memory (live \d output)

No `priority` column. Columns: id, workspace_id, user_id, session_id, role, content, embedding, memory_type, persistent, created_at, tier, importance_score, last_accessed_at, summary, access_count, content_rating.

### alpha_semantic_memory (live \d output)

No `priority` column. Columns: id, user_id, fact, category, source, created_at, updated_at.

### alpha_task_events (live \d output — DIVERGENT FROM MIGRATION)

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
Check constraints:
    "alpha_task_events_severity_check" CHECK (severity IN ('low','normal','warning','critical'))
```

**NOTE:** Migration 008b_task_events.sql created this table with column `priority TEXT`. The live schema has `severity TEXT` instead. The column was renamed at some point (no tracked migration found for this rename). Both `watchdog.py:112` and `executor.py:498` still INSERT into `priority` — a column that no longer exists. This is a **separate latent bug** that will throw `column "priority" does not exist` if either code path is triggered.

### Broad sweep — ALL priority columns in jarvis_alpha

```
     table_name     | column_name | data_type | is_nullable | column_default
--------------------+-------------+-----------+-------------+----------------
 alpha_buddy_events | priority    | integer   | NO          | 2
 alpha_task_graphs  | priority    | integer   | NO          | 5
(2 rows)
```

Only two tables have a `priority` column, both INTEGER. No triggers on `alpha_buddy_events`.

---

## 3. Migration History for Priority

Chronological order of all migrations touching `priority`:

| Migration | Applied (UTC) | What it does |
|-----------|---------------|--------------|
| `005_buddy_events.sql` | pre-tracking (backfill) | Creates `alpha_buddy_events.priority INT NOT NULL DEFAULT 2` |
| `008b_task_events.sql` | pre-tracking (backfill) | Creates `alpha_task_events.priority TEXT NOT NULL DEFAULT 'normal'` with CHECK constraint |
| `011_buddy_events_columns.sql` | pre-tracking (backfill) | Adds `source` and `payload` columns to alpha_buddy_events (no priority change) |
| `20260408_130000_security_definer_functions.sql` | 2026-04-08 20:08 UTC | **THE BUG**: Creates `record_buddy_event(p_priority TEXT)` — TEXT parameter vs INTEGER column |
| `20260408_140000_record_buddy_event_fix.sql` | 2026-04-08 20:39 UTC | **THE FIX**: Drops TEXT-signature function, recreates with `p_priority INTEGER`, return type corrected from BIGINT to UUID |
| `20260408_150000_evict_fix_and_promote_rip.sql` | 2026-04-08 22:05 UTC | Drops promote function, fixes evict logic. No priority change. |

**The priority column type has never changed.** It was always INTEGER in the table. The bug was purely in the SECDEF function parameter type.

Unknown: When `alpha_task_events.priority` was renamed to `severity`. No tracked migration for this change. The column name in the live DB (`severity`) differs from both the 008b migration (`priority`) and the code (`priority`).

---

## 4. SECDEF Functions from Stage 5c

### Live function signatures and bodies

**record_buddy_event** (fixed version, OID 35624):
```
Signature: (p_user_id text, p_event_type text, p_title text, p_body text, p_priority integer, p_source text, p_payload jsonb) → uuid
```
Body: INSERT INTO alpha_buddy_events with all parameters mapped 1:1. Re-raises all exceptions.

**get_buddy_promotion_candidates** (Stage 5c, migration 20260409_130000):
```
Signature: (p_user_id text) → TABLE(id uuid, summary text)
```
Body: SELECT from alpha_conversation_memory WHERE tier='working' AND created_at < now() - 20 hours. No priority reference.

**list_active_memory_users** (Stage 5c, migration 20260409_130000):
```
Signature: () → text[]
```
Body: SELECT DISTINCT user_id FROM alpha_conversation_memory. No priority reference.

**run_buddy_memory_maintenance** (original 130000, modified 150000):
```
Signature: (p_user_id text) → jsonb
```
Body: Calls evict_expired_working_memory(), evict_episodic_memory_older_than(), cap_episodic_memory(), cap_semantic_memory(). Promote step removed in 150000. No priority reference in any sub-function.

**No function overloads exist.** Only one `record_buddy_event` function in `pg_proc` (OID 35624, INTEGER signature).

---

## 5. Affected Users' Data

### Buddy events for affected users

```
               user_id                | event_type | count
--------------------------------------+------------+-------
 5516a432-35ab-5ac7-8521-dfd3b867c3b6 | alert      |   749
 5516a432-35ab-5ac7-8521-dfd3b867c3b6 | system     |  2265
 17eaebb1-d614-5558-bf31-df498d7a61b6 | alert      |  1034
 17eaebb1-d614-5558-bf31-df498d7a61b6 | system     |  2666
```

All existing buddy_events rows for these users have `priority = 3, pg_typeof = integer` — these were written successfully AFTER the fix.

Date ranges:
```
 5516a432... | first: 2026-04-08 20:39:41 | last: 2026-04-10 10:18:19 | 3014 rows
 17eaebb1... | first: 2026-04-02 16:25:28 | last: 2026-04-10 15:31:23 | 3706 rows
```

User 5516a432's first successful buddy_event was at 20:39:41 UTC — 8 seconds after the fix migration was applied at 20:39:33 UTC. This confirms the fix resolved the error immediately.

### Conversation memory for affected users

```
 17eaebb1-d614-5558-bf31-df498d7a61b6 | episodic | 25
 (5516a432... has 0 rows — working-tier rows were evicted by maintenance)
```

### Why only these two users?

At the time of the error (2026-04-08 20:08-20:39 UTC), these were the only two users with rows in `alpha_conversation_memory`. The buddy loop calls `list_active_memory_users()` which returns `DISTINCT user_id FROM alpha_conversation_memory`, then iterates over each user calling maintenance + write_event. Users without memory rows are never iterated.

---

## 6. The Exact Line That Throws the Error

The error originates from the **body of the SECDEF function** `record_buddy_event` as it existed between migrations 130000 and 140000.

### The buggy function (migration 20260408_130000, lines 10-47):

```sql
CREATE OR REPLACE FUNCTION public.record_buddy_event(
  p_user_id TEXT,
  p_event_type TEXT,
  p_title TEXT,
  p_body TEXT,
  p_priority TEXT,        -- <<< BUG: TEXT parameter
  p_source TEXT,
  p_payload JSONB
) RETURNS BIGINT          -- <<< ALSO WRONG: should be UUID
...
  INSERT INTO public.alpha_buddy_events
    (user_id, event_type, title, body, priority, source, payload)
  VALUES
    (p_user_id, p_event_type, p_title, p_body, p_priority, p_source, p_payload)
                                                ^^^^^^^^^^
                                                TEXT value going into INTEGER column
  RETURNING id INTO v_id;
```

**PostgreSQL error**: When the INSERT executes inside the function body, `p_priority` is TEXT (e.g., `'1'`, `'2'`, `'3'` — serialized by asyncpg from the Python int according to the function's TEXT parameter type). The `alpha_buddy_events.priority` column is INTEGER with no implicit TEXT→INTEGER cast in this context. PostgreSQL raises: `column "priority" is of type integer but expression is of type text`.

### The Python call chain leading here:

```
buddy_agent.py:170  logger.error("Buddy cycle error for user %s: %s", user_id, e)
buddy_agent.py:169  except Exception as e:
buddy_agent.py:143  await _write_event(pool, ..., priority=1, ...)   ← OR line 160 with priority=3
buddy_agent.py:60   p_priority = _normalize_buddy_priority(priority)  → returns int 1 or 3
buddy_agent.py:64   conn.fetchval("SELECT public.record_buddy_event($1,$2,$3,$4,$5,$6,$7)", ..., p_priority, ...)
                    ↓
                    asyncpg prepares the statement, PostgreSQL resolves $5 as TEXT (from function signature)
                    asyncpg encodes Python int 1 as TEXT '1'
                    ↓
                    SECDEF function body: INSERT ... VALUES (..., '1'::TEXT, ...) into INTEGER column → ERROR
```

---

## 7. Buddy Cycle Flow

### Entry point: `buddy_agent.py:175` — `run_buddy()`

```
run_buddy()                              # line 175
  pool = asyncpg.create_pool(DSN)        # line 180 — uses ALPHA_DB_DSN_BUDDY
  while True:                            # line 183
    _run_cycle(pool)                     # line 185 — top-level try/except at 184-187
    sleep(60)                            # line 189
```

### Main cycle: `_run_cycle()` (line 124)

```
_run_cycle(pool):
  1. _expire_pending_approvals(pool)              # line 126 — own try/except, never touches priority
  2. users = list_active_memory_users() via SECDEF # line 128-131
  3. FOR each user_id in users:                    # line 133
       TRY:                                        # line 136
         a. maintenance = run_buddy_memory_maintenance(user_id)  # line 138-141, SECDEF
         b. _write_event(priority=1, payload=maintenance)        # line 143-151 ← FAILS HERE
         c. aging = get_buddy_promotion_candidates(user_id)      # line 153-157, SECDEF
         d. IF aging: _write_event(priority=3)                   # line 159-167 ← OR FAILS HERE
       EXCEPT Exception as e:                                    # line 169
         logger.error("Buddy cycle error for user %s: %s", ...)  # line 170
```

### Error swallowing

The per-user `try/except` at lines 136-170 catches **all** exceptions and logs them. The cycle continues to the next user. The top-level `while True` loop (line 183) also has its own try/except (lines 184-187) that catches top-level errors. This is why buddy loops forever without crashing — the error is logged and swallowed every 60 seconds.

### Specific failure point

For the error period, step (b) — `_write_event(priority=1)` at line 143 — is the first call to `record_buddy_event` per user. It fails, the exception is caught at line 169, and the cycle moves to the next user. Steps (c) and (d) are never reached for that user during the error window.

---

## Root Cause Hypothesis

Migration `20260408_130000_security_definer_functions.sql` created the `record_buddy_event` SECDEF function with `p_priority TEXT`, but the `alpha_buddy_events.priority` column has always been `INTEGER` (since migration `005_buddy_events.sql`). When the function body executed `INSERT INTO alpha_buddy_events (..., priority, ...) VALUES (..., p_priority, ...)`, PostgreSQL rejected the implicit TEXT-to-INTEGER assignment because PL/pgSQL INSERT assignment follows strict typing (no implicit text→integer cast). The bug was introduced at 20:08 UTC on 2026-04-08 when migration 130000 was applied, and fixed 31 minutes later at 20:39 UTC when migration 140000 dropped the TEXT-signature function and recreated it with the correct `p_priority INTEGER` parameter. The error is **no longer active** — 64 total error entries were logged across 32 buddy cycles (2 users x 32 cycles), and buddy has been running cleanly since the fix. The two affected users were simply the only users with `alpha_conversation_memory` rows at the time, making them the only users the buddy loop iterated over.

---

## Assumptions

1. Migration applied_at timestamps in `schema_migrations` are in the Brain's local timezone (ET / UTC-4). Converted to UTC for comparison with log timestamps.
2. The buddy agent process was running continuously throughout the error window and was not restarted between migrations 130000 and 140000 — asyncpg's prepared statement cache was refreshed automatically when PostgreSQL invalidated it after the DROP+CREATE in migration 140000.
3. User 5516a432's conversation_memory rows existed at the time of the error but have since been evicted by buddy's maintenance cycle (evict_expired_working_memory deletes working-tier rows older than 24h).

## Items That Could Not Be Verified

1. **When `alpha_task_events.priority` was renamed to `severity`**: No tracked migration for this schema change. The live table has `severity` but migration 008b and the code reference `priority`. This is a separate latent bug — watchdog.py:112 and executor.py:498 will fail with "column priority does not exist" if their INSERT paths are triggered.
2. **Whether the buddy process was restarted between migrations 130000 and 140000**: Logs show continuous 60-second cycles with no gaps, suggesting the process was not restarted. The fix took effect via asyncpg's automatic prepared statement invalidation after the DROP FUNCTION.
3. **Original conversation_memory rows for user 5516a432**: These were evicted before this investigation. We can infer they existed because (a) the user appeared in the buddy loop's iteration, and (b) the user's first successful buddy_event was written at 20:39:41 UTC, immediately after the fix.
