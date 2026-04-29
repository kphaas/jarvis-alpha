# BUDDY_PRIORITY_BUG_FORENSIC

**Investigation date:** 2026-04-29
**Investigator:** Claude (forensic, read-only)
**Symptom:** `column "priority" is of type integer but expression is of type text` in `brain/agents/buddy_agent.py` cycles, two affected user UUIDs, errors first observed 2026-04-08.

**Headline:** This bug is **already fixed and has not recurred since 2026-04-08 20:39:25 UTC**. The "every cycle since 2026-04-08" framing is misleading — errors occurred for **31 minutes only** (2026-04-08 20:08 → 20:39 UTC), then stopped permanently when migration `20260408_140000_record_buddy_event_fix.sql` was applied. The currently-running buddy is healthy.

---

## 1. Offending SQL — file, line numbers, full statement

The error does **not** originate from a Python-side `INSERT` or `UPDATE`. The Python code in `brain/agents/buddy_agent.py` calls a SECURITY DEFINER function `public.record_buddy_event(...)` and never INSERTs into `alpha_buddy_events` directly. The offending INSERT lived inside the SQL function body.

### Python call site (correct, not the bug)

`/Users/jarvissand/jarvis-alpha/brain/agents/buddy_agent.py:63-73`

```python
async with pool.acquire() as conn:
    return await conn.fetchval(
        "SELECT public.record_buddy_event($1, $2, $3, $4, $5, $6, $7)",
        user_id if user_id else "system",
        p_event_type,
        title,
        body,
        p_priority,         # already coerced to int by _normalize_buddy_priority
        source,
        payload_json,
    )
```

The Python normalizer (`buddy_agent.py:30-42`) returns a Python `int`. asyncpg binds it to the function's declared parameter type. The Python side was never the problem.

### Offending function body (the actual bug)

`/Users/jarvissand/jarvis-alpha/brain/db/migrations/20260408_130000_security_definer_functions.sql:10-47`

```sql
CREATE OR REPLACE FUNCTION public.record_buddy_event(
  p_user_id TEXT,
  p_event_type TEXT,
  p_title TEXT,
  p_body TEXT,
  p_priority TEXT,         -- <<< BUG: declared TEXT
  p_source TEXT,
  p_payload JSONB
) RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_id BIGINT;
BEGIN
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  IF p_user_id IS NULL OR p_user_id = '' THEN
    RAISE EXCEPTION 'record_buddy_event: p_user_id must be non-null ...'
      USING ERRCODE = '22023';
  END IF;

  INSERT INTO public.alpha_buddy_events
    (user_id, event_type, title, body, priority, source, payload)   -- <<< priority is INTEGER column
  VALUES
    (p_user_id, p_event_type, p_title, p_body, p_priority, p_source, p_payload)
                                                ^^^^^^^^^^
                                                TEXT bound to INTEGER column → error
  RETURNING id INTO v_id;

  RETURN v_id;
EXCEPTION
  WHEN OTHERS THEN
    RAISE;     -- audit-critical, re-raises so the agent log captures it
END;
$$;
```

**Other places mentioning a `priority` column** (none of them are bugs in scope):
- `brain/planner.py:33` — kwarg, not SQL
- `brain/dream/activities.py:55` — kwarg, not SQL
- `brain/routes/tasks.py:330` — body parse from request
- `brain/services/approval_notifier.py:109` — local var, passes to `record_buddy_event` (currently fine)
- `brain/db/migrations/20260408_140000_record_buddy_event_fix.sql:33` — the FIX (correct types)

No buddy code path performs a direct `INSERT INTO alpha_buddy_events` or `UPDATE alpha_buddy_events SET priority=...`. All writes funnel through `record_buddy_event`.

---

## 2. Target table(s) — confirmed via `\d` on Brain

DB: `jarvis_alpha` on host `jarvis-brain.tail40ed36.ts.net` (user `jarvisbrain`).

### `public.alpha_buddy_events` — has `priority` column, type **INTEGER**

```
                        Table "public.alpha_buddy_events"
   Column   |           Type           | Nullable |      Default
------------+--------------------------+----------+-------------------
 id         | uuid                     | not null | gen_random_uuid()
 user_id    | text                     |          |
 event_type | text                     | not null |
 title      | text                     | not null |
 body       | text                     |          |
 priority   | integer                  | not null | 2          <<< INTEGER
 read       | boolean                  | not null | false
 created_at | timestamp with time zone | not null | now()
 source     | text                     |          |
 payload    | jsonb                    |          |
```

This is the table the buddy error references. The `priority INTEGER NOT NULL DEFAULT 2` shape has been the live schema since migration `005_buddy_events.sql`.

### `public.alpha_task_graphs` — has `priority` column, type **INTEGER** (irrelevant to this bug)

```
 priority | integer | not null | 5
Check constraints:
    "alpha_task_graphs_priority_check" CHECK (priority >= 1 AND priority <= 10)
```

No buddy code touches `alpha_task_graphs.priority`; that column is used by planner / task-graph code only.

### `public.alpha_task_steps` — does NOT have a `priority` column

Confirmed via `\d alpha_task_steps`. No `priority` column exists. This table was a red herring in the symptom report.

---

## 3. Type mismatch root cause

**Root cause:** Migration `20260408_130000_security_definer_functions.sql` defined the SECURITY DEFINER wrapper `record_buddy_event` with parameter `p_priority TEXT`. The function body's `INSERT INTO alpha_buddy_events (..., priority, ...) VALUES (..., p_priority, ...)` then attempted to assign that `TEXT` value into the `priority INTEGER` column.

PL/pgSQL `INSERT ... VALUES (...)` does **strict typing on column assignment** — there is no implicit cast from `text` to `integer`. PostgreSQL therefore raised:

```
column "priority" is of type integer but expression is of type text
HINT:  You will need to rewrite or cast the expression.
```

**What buddy was passing:** A Python `int` (e.g. `1`, `2`, `3`) — verified by `_normalize_buddy_priority` at `buddy_agent.py:30-42`, which always returns `int`. asyncpg, when given an int and a function whose declared parameter is `TEXT`, performs the bind by emitting the literal as text (`'1'`, `'2'`, `'3'`). Inside the function, `p_priority` is therefore the text string `'1'` etc., and the INSERT into the integer column blows up.

So the chain is:

1. Python `_normalize_buddy_priority` → int (e.g. `1`)
2. asyncpg binds to `record_buddy_event(...)` whose 5th param is declared `TEXT` → coerced to text `'1'`
3. Function body `INSERT ... VALUES (..., p_priority, ...)` tries to assign `'1'::text` into `alpha_buddy_events.priority` (INTEGER) → **ERROR**

The Python f-string / unquoted-variable theory in the symptom statement was a misread; the bug is purely in the SQL function signature.

---

## 4. Liveness check — IS THIS STILL HAPPENING? **No.**

### Sandbox `~/jarvis-alpha/logs/`

```
total 8
drwxr-xr-x  5 jarvissand  staff  160 Apr 29 17:51 td132_orphan_cleanup_20260429
-rw-r--r--  1 jarvissand  staff  163 Apr 28 07:27 test.log
```

Sandbox has no buddy logs. Buddy runs on Brain.

### Brain `~/jarvis-alpha/logs/` (latest by mtime)

```
-rw-r--r-- 1 jarvisbrain staff   7873052 Apr 29 18:45 alpha_buddy.log
```

`alpha_buddy.log` is the active log; mtime 2026-04-29 18:46:51 EDT. Covers 2026-04-04 → present (continuous, not rotated).

### Grep for `is of type integer` in active log

```
$ grep -c 'is of type integer' ~/jarvis-alpha/logs/alpha_buddy.log
64
```

**64 total occurrences.** First and last:

```
First: {"ts": "2026-04-08T20:08:25.319169+00:00", "trace_id": "78d9440366fd",
        "message": "Buddy cycle error for user 17eaebb1-d614-5558-bf31-df498d7a61b6: ..."}

Last:  {"ts": "2026-04-08T20:39:25.678807+00:00", "trace_id": "5a16429ef291",
        "message": "Buddy cycle error for user 5516a432-35ab-5ac7-8521-dfd3b867c3b6: ..."}
```

**Latest occurrence: 2026-04-08T20:39:25Z. Zero occurrences in the 21 days since.**

64 errors = 32 buddy cycles × 2 users (the only two users with `alpha_conversation_memory` rows at the time, hence the only two iterated by `list_active_memory_users()`).

Recent buddy log tail (2026-04-29 22:45 UTC) shows clean cycle completions:

```
{"ts": "2026-04-29T22:45:51.641833+00:00", "level": "INFO", "service": "alpha_buddy",
 "message": "Buddy cycle complete at 2026-04-29T22:45:51.641616+00:00"}
```

### Schema-migration corroboration

```
                    filename                    |       applied_at
------------------------------------------------+-----------------------------
 20260408_130000_security_definer_functions.sql | 2026-04-08 16:08:16.917-04   = 20:08 UTC
 20260408_140000_record_buddy_event_fix.sql     | 2026-04-08 16:39:33.046-04   = 20:39 UTC
```

Migration apply timestamps line up to the second with first/last error timestamps. The 31-minute error window is exactly the gap between the broken migration applying and the fix migration applying.

### Live function signature on Brain (post-fix, single signature, no overload)

```
$ \df+ public.record_buddy_event
 Schema |        Name        | Result | Argument data types
--------+--------------------+--------+----------------------------------------------
 public | record_buddy_event | uuid   | p_user_id text, p_event_type text, p_title text,
        |                    |        | p_body text, p_priority integer,
        |                    |        | p_source text, p_payload jsonb
```

```
$ SELECT proname, prorettype::regtype, proargtypes::regtype[] FROM pg_proc
  WHERE proname='record_buddy_event';
      proname       | prorettype |                  proargtypes
--------------------+------------+------------------------------------------------
 record_buddy_event | uuid       | [0:6]={text,text,text,text,integer,text,jsonb}
(1 row)
```

Single signature, `p_priority integer`. No leftover `TEXT` overload.

`alpha_buddy_events` row count: **47,185** — buddy is writing successfully.

---

## 5. Proposed minimal fix — already applied (no further action needed)

The fix is the file `brain/db/migrations/20260408_140000_record_buddy_event_fix.sql`, applied 2026-04-08 20:39 UTC. Effective diff between the two SQL functions:

```diff
--- 20260408_130000_security_definer_functions.sql  (broken)
+++ 20260408_140000_record_buddy_event_fix.sql      (fix)
@@ -1,4 +1,7 @@
+DROP FUNCTION IF EXISTS public.record_buddy_event(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB);
+
 CREATE OR REPLACE FUNCTION public.record_buddy_event(
   p_user_id TEXT,
   p_event_type TEXT,
   p_title TEXT,
   p_body TEXT,
-  p_priority TEXT,
+  p_priority INTEGER,
   p_source TEXT,
   p_payload JSONB
-) RETURNS BIGINT
+) RETURNS UUID
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = pg_catalog, public, pg_temp
 AS $$
 DECLARE
-  v_id BIGINT;
+  v_id UUID;
 BEGIN
   ...
@@ -44,5 +47,5 @@
-REVOKE EXECUTE ON FUNCTION public.record_buddy_event(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB) FROM PUBLIC;
-GRANT EXECUTE ON FUNCTION public.record_buddy_event(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB) TO jarvis_alpha_writer;
-GRANT EXECUTE ON FUNCTION public.record_buddy_event(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB) TO jarvisbrain;
+REVOKE EXECUTE ON FUNCTION public.record_buddy_event(TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, JSONB) FROM PUBLIC;
+GRANT EXECUTE ON FUNCTION public.record_buddy_event(TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, JSONB) TO jarvis_alpha_writer;
+GRANT EXECUTE ON FUNCTION public.record_buddy_event(TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, JSONB) TO jarvisbrain;
```

Two changes were required and made:
1. **`p_priority TEXT` → `p_priority INTEGER`** to match the column type.
2. **`RETURNS BIGINT` → `RETURNS UUID`**, **`v_id BIGINT` → `v_id UUID`** — `alpha_buddy_events.id` is a `uuid`, not `bigint`. (Even after fixing priority, the BIGINT return would still have errored on the `RETURNING id INTO v_id` assignment.)

No further fix is needed. The only outstanding hygiene item would be:

- **Optional cleanup:** consider archiving / deleting migration `20260408_130000_security_definer_functions.sql`'s `record_buddy_event` definition or replacing it with the fixed version, so a fresh DB rebuild from migrations has a single correct function. Today, replaying both migrations in order works (130000 creates broken, 140000 drops + recreates correct), but it briefly creates and drops the broken signature. Per `docs/TD32_GHOST_MIGRATION_CLEANUP.md`, this is already tracked as TD32 ghost-migration cleanup.

No Python edits are needed. `_normalize_buddy_priority` correctly emits `int`.

---

## 6. Blast radius if it had been left unfixed

### What buddy does

`brain/agents/buddy_agent.py` runs every 60 seconds (`BUDDY_INTERVAL_SECONDS=60`) on Brain and per-user it:

1. Calls `expire_pending_approvals()` (independent of priority bug).
2. For each user in `list_active_memory_users()`:
   a. `run_buddy_memory_maintenance(user_id)` — evicts working memory, ages out episodic, caps episodic/semantic, promotes episodic→semantic.
   b. `_write_event(... priority=1 ...)` to log "Memory maintenance complete" (system event).
   c. `get_buddy_promotion_candidates(user_id)` — find rows expiring in <4h.
   d. If any: `_write_event(... priority=3 ...)` "N working memories expiring soon" alert.

### What the failed write blocked

The exception thrown by step (b) was caught at `buddy_agent.py:133-134`:

```python
except Exception as e:
    logger.error("Buddy cycle error for user %s: %s", user_id, e)
```

The exception aborts the per-user `try` block, so for the affected user **steps (c) and (d) were skipped that cycle**. Specifically:

- **Memory-maintenance side-effects (step a) had already committed** before the failing write — `run_buddy_memory_maintenance` is its own SECDEF function with its own transaction. Eviction, capping, and promotion still ran successfully. No memory loss.
- **The "maintenance complete" buddy event (step b) was lost** — these system-tier audit events did not land in `alpha_buddy_events` for the affected users during the 31-minute window. ~32 events × 2 users = ~64 missing audit rows.
- **The "expiring soon" alert (step d) was never reached.** If either named user had memories about to be evicted in <4h during that window, they did not receive the in-app alert. Given the short window (31 min) and the 4-hour expiry horizon, anything that was about to expire would still have been re-flagged on the very next healthy cycle at 20:40 UTC, so no alert was permanently lost — only delayed by at most one cycle.
- **No data corruption.** The INSERT failure was atomic; nothing partial got written.

### Were the two named users specifically affected, or is it broader?

The two users `17eaebb1-d614-5558-bf31-df498d7a61b6` and `5516a432-35ab-5ac7-8521-dfd3b867c3b6` were affected because they were the only members of `list_active_memory_users()` at the time (the only users with rows in `alpha_conversation_memory`). The bug affected **every user the buddy loop iterated over** — it is not user-specific. If more users had been active, all of them would have hit the same error.

The bug is **service-wide** for `record_buddy_event`, but its real-world blast was bounded by:
- 31-minute live window (130000 → 140000 migration gap).
- Only 2 users active.
- All Buddy "system" / "alert" events were affected (and `approval_notifier.send_approval_notification` at `brain/services/approval_notifier.py:109` also calls `record_buddy_event` and would have failed identically — no approval notifications fired during that window). Live `schema_migrations` shows no approval-flow activity in that window, so no actual approval events were lost.

### Counterfactual: had the fix not landed in 31 minutes

Buddy would have continued logging two errors per minute per active user, indefinitely. Memory-maintenance eviction/promotion would still have executed (they're separate SECDEF calls), so no memory tier overflow. But:
- `alpha_buddy_events` would receive zero rows from buddy cycles.
- All in-app "expiring memory" alerts would be permanently silent.
- `approval_notifier` would error every time, blocking T5 / T1 approval notifications.
- The `alpha_buddy.log` ERROR rate would attract attention, which is essentially what happened: the error was caught and fixed within 31 minutes.

---

## Appendix — evidence inventory

| Item | Location |
|---|---|
| Buggy SQL | `/Users/jarvissand/jarvis-alpha/brain/db/migrations/20260408_130000_security_definer_functions.sql:10-47` |
| Fix SQL | `/Users/jarvissand/jarvis-alpha/brain/db/migrations/20260408_140000_record_buddy_event_fix.sql:1-49` |
| Python caller | `/Users/jarvissand/jarvis-alpha/brain/agents/buddy_agent.py:30-73` |
| Active buddy log | `jarvisbrain@jarvis-brain:~/jarvis-alpha/logs/alpha_buddy.log` (mtime 2026-04-29 18:46) |
| Prior root-cause doc | `/Users/jarvissand/jarvis-alpha/docs/TD46_DISCOVERY.md` |
| Stage 4 schema confirmation | `/Users/jarvissand/jarvis-alpha/docs/STAGE4_DISCOVERY.md` (lines 92, 100, 191-196) |
| Ghost migration cleanup tracker | `/Users/jarvissand/jarvis-alpha/docs/TD32_GHOST_MIGRATION_CLEANUP.md` |

**SSH/DB invocation cheatsheet (used to gather evidence):**
```bash
ssh jarvisbrain@jarvis-brain.tail40ed36.ts.net \
  "/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -d jarvis_alpha -U jarvisbrain -c '\d alpha_buddy_events'"

ssh jarvisbrain@jarvis-brain.tail40ed36.ts.net \
  "grep -c 'is of type integer' ~/jarvis-alpha/logs/alpha_buddy.log"
# → 64

ssh jarvisbrain@jarvis-brain.tail40ed36.ts.net \
  "grep 'is of type integer' ~/jarvis-alpha/logs/alpha_buddy.log | tail -1"
# → ts: 2026-04-08T20:39:25.678807+00:00
```
