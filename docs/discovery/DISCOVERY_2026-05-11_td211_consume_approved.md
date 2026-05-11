# DISCOVERY — TD-211 `consume_approved_queue_item()` SECDEF silent failure

- **Date:** 2026-05-11
- **Scope:** Read-only root-cause investigation for TD-211. Determine whether Slab 4 Phase 2 fleet write fix addresses TD-211 or whether a targeted PR is required.
- **Author:** Claude Code (read-only discovery)
- **Local repo HEAD:** `a2f5980` 2026-05-11 10:57:28 -0400 `feat(F-A-smoke-002): TD-68 delete dead stub brain/model_router.py (#86)`

## Spec drift notes (raised before proceeding)

The user-supplied procedure referenced `approval_queue`, columns `kind` and `error`, and `pg_tables.forcerowsecurity`. None of these exist in production. The actual schema is:

- Table name: `public.alpha_approval_queue` (no unprefixed `approval_queue` table)
- Column for action category: `action_class text[]` (no `kind`)
- No `error` column on `alpha_approval_queue`
- `forcerowsecurity` is in `pg_class.relforcerowsecurity`, not `pg_tables`

These are spec-template differences, not blockers; the function, table, and live data are unambiguously identified. Proceeded with corrected identifiers and flagged in the doc per instructions.

---

## Section 1 — Function definition (`pg_get_functiondef`)

```sql
CREATE OR REPLACE FUNCTION public.consume_approved_queue_item(p_queue_id uuid)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
BEGIN
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    UPDATE public.alpha_approval_queue
       SET status = 'executed',
           executed_at = NOW()
     WHERE id = p_queue_id;
END;
$function$
```

Observations:

- Function body is **purely a state transition** — it does NOT execute the approved destructive action. The caller is responsible for executing the action separately; this function only marks the row `executed`.
- Function body does NOT call `set_config('rls.role', 'platform_admin', true)` or any equivalent. It relies on its `SECURITY DEFINER` definer (owner = `jarvisbrain`) to satisfy RLS.
- No `RETURNING`, no row-count check (e.g., `IF NOT FOUND THEN RAISE`). If the UPDATE matches zero rows, the function returns silently.

## Section 2 — Function metadata

```
           proname           | prosecdef |      proconfig       | provolatile | prorettype
-----------------------------+-----------+----------------------+-------------+------------
 consume_approved_queue_item | t         | {search_path=public} | v           | void
```

```
  proowner   | prosecdef |      proconfig
-------------+-----------+----------------------
 jarvisbrain | t         | {search_path=public}
```

- `prosecdef = t` ✅ SECDEF.
- `proconfig` carries only `search_path=public`. **No `rls.role` setting.** ← pattern-hole indicator.
- Owner is `jarvisbrain` (rolsuper=t, rolbypassrls=t). Because the owner is superuser, FORCE RLS is bypassed when the function body executes. So *if the function were called*, its UPDATE would succeed regardless of session `rls.role`.

Grants (from pg log audit):

- `REVOKE ALL ... FROM PUBLIC; GRANT ALL ... TO jarvis_alpha_app; GRANT ALL ... TO jarvis_alpha_writer;`

## Section 3 — FORCE RLS status on touched tables

Function body touches exactly one table: `public.alpha_approval_queue`.

```
 nspname |       relname        | relrowsecurity | relforcerowsecurity
---------+----------------------+----------------+---------------------
 public  | alpha_approval_queue | t              | t
```

Active policy (from `\d alpha_approval_queue`):

```
Policies (forced row security enabled):
    POLICY "approval_queue_isolation"
      USING ((current_setting('rls.role'::text, true) = 'platform_admin'::text))
      WITH CHECK ((current_setting('rls.role'::text, true) = 'platform_admin'::text))
```

Confirmed via pg audit log on 2026-05-01: `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` + `CREATE POLICY approval_queue_isolation`.

**Role bypass map** (pg_roles):

```
       rolname        | rolbypassrls | rolsuper | rolcanlogin
----------------------+--------------+----------+-------------
 jarvisbrain          | t            | t        | t
 jarvis_alpha_app     | f            | f        | f
 jarvis_alpha_writer  | f            | f        | t
```

The pool writer connections come up as `jarvis_alpha_writer` (`rolbypassrls=f`, `rolsuper=f`). Confirmed live via `pg_stat_activity`:

```
       usename       | application_name | client_addr | state
---------------------+------------------+-------------+--------
 jarvis_alpha_writer |                  | ::1         | idle
 jarvis_alpha_writer |                  | ::1         | idle
 jarvis_alpha_writer |                  | ::1         | idle
 jarvis_alpha_writer |                  | ::1         | idle
 jarvis_alpha_writer |                  | ::1         | idle
```

→ FORCE RLS does apply to pool connections. The session must have `rls.role='platform_admin'` to SELECT or UPDATE `alpha_approval_queue`.

## Section 4 — Caller path

Single Python hit (sandbox repo at `a2f5980`, fresh-pulled today):

```
brain/middleware/approval.py
```

Two relevant methods:

### `_get_approved_queue_id` — brain/middleware/approval.py:139

```python
async def _get_approved_queue_id(self, actor_sub, parameters_hash):
    pool = get_pool()
    if not pool:
        logger.error("no DB pool available for approval queue read")
        return None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id
               FROM alpha_approval_queue
               WHERE actor_sub = $1
                 AND parameters_hash = $2
                 AND status = 'approved'
                 AND expires_at > NOW()
               ORDER BY requested_at DESC
               LIMIT 1""",
            actor_sub, parameters_hash,
        )
    return str(row["id"]) if row else None
```

- Acquires a **raw pool connection** (no role swap, no `rls_connection()`).
- Connection runs as `jarvis_alpha_writer` with no `rls.role` set.
- FORCE RLS on `alpha_approval_queue` → policy `current_setting('rls.role', true) = 'platform_admin'` evaluates to `false` (current_setting with `missing_ok=true` returns empty string, ≠ 'platform_admin').
- Result: query silently returns **0 rows** even when approved rows exist.

### `_consume_approved_queue` — brain/middleware/approval.py:163

```python
async def _consume_approved_queue(self, queue_id: str) -> None:
    pool = get_pool()
    if not pool:
        logger.error("no DB pool available for approval consume write")
        return

    async with pool.acquire() as conn:
        await conn.execute(
            "SELECT public.consume_approved_queue_item($1::uuid)",
            queue_id,
        )
```

- Also a raw pool connection, no `rls.role` set.
- Inside the SECDEF function, the UPDATE would succeed (owner = jarvisbrain = superuser bypasses FORCE RLS).
- **No try/except**: any exception inside the function call would propagate to the middleware's `dispatch` and surface as a 500. But because the function silently does nothing wrong when called, this branch is irrelevant — it is never reached (see below).

### Dispatch flow — approval.py:90-97

```python
approved_queue_id = await self._get_approved_queue_id(
    actor_sub=actor_sub,
    parameters_hash=parameters_hash,
)
if approved_queue_id:
    response = await call_next(request)
    await self._consume_approved_queue(approved_queue_id)
    return response

# Queue for approval  ← falls through to here when read returns None
```

Because `_get_approved_queue_id` returns `None` under FORCE RLS, the middleware *always* falls through to re-queue, and `_consume_approved_queue` is *never* called.

### Contrast: canonical RLS pattern — brain/db/rls.py

`brain/db/rls.py:rls_connection()` is the canonical helper. It:

1. Acquires pool conn.
2. `SET ROLE jarvis_alpha_app`.
3. Inside `conn.transaction()`, calls `set_config('rls.user_id'/'rls.role'/'rls.max_rating'/'rls.workspace_id', …, true)` (LOCAL, transaction-scoped).
4. Yields conn.
5. `RESET ROLE` on exit.

`brain/middleware/approval.py` does NOT use this helper. It uses raw `pool.acquire()` directly.

## Section 5 — Live `alpha_approval_queue` state

```
                  id                  | action_class  | risk_tier |  status  |         requested_at          |          decided_at           | executed_at
--------------------------------------+---------------+-----------+----------+-------------------------------+-------------------------------+-------------
 64bbbb8f-7214-46e7-a15d-fb0ceb2e461b | {destructive} | T5        | approved | 2026-05-09 10:27:49.731634-04 | 2026-05-09 10:28:02.815085-04 |
 2966166d-d014-48dd-92cb-75b5a7c5b905 | {destructive} | T5        | approved | 2026-05-09 10:21:24.283007-04 | 2026-05-09 10:21:45.05302-04  |
 9dadbfa3-ad2d-433b-9876-80ed8cc83571 | {destructive} | T5        | approved | 2026-05-09 10:20:42.220158-04 | 2026-05-09 10:20:55.988323-04 |
 59ec0534-8ecb-429a-8ad8-db92d75be966 | {destructive} | T5        | approved | 2026-05-09 10:19:58.675124-04 | 2026-05-09 10:20:08.479995-04 |
 2e18f89a-0b15-4a73-b452-5681c24594ba | {destructive} | T5        | approved | 2026-05-09 10:19:34.30917-04  | 2026-05-09 10:19:48.490095-04 |
 c7765f0a-354b-4265-9b76-8ae1f194add7 | {destructive} | T5        | approved | 2026-05-08 11:24:09.812241-04 | 2026-05-08 11:24:46.884321-04 |
 8f6a32f4-1c81-4da7-ace3-a5015002e486 | {destructive} | T5        | approved | 2026-05-08 11:20:22.239531-04 | 2026-05-08 11:23:56.625738-04 |
 5c9b12a8-965d-403c-82d4-2cb1e7b67ec2 | {destructive} | T5        | expired  | 2026-05-09 10:28:07.679982-04 |                               |
 1e923a6d-b4b1-4848-ae97-bbcb9f5b0c26 | {destructive} | T5        | approved | 2026-05-07 19:09:21.644239-04 |                               |
```

**Silent-failure rows (status=`approved` AND executed_at IS NULL): 8** — spanning 2026-05-07 → 2026-05-09. TD-211 is live and reproducible.

Note: row `1e923a6d` is `approved` with NULL `decided_at` — likely state-restored after a TRUNCATE on 2026-05-07 19:03 (visible in pg audit). Even the more recent, properly decided approvals never executed.

## Section 6 — Recent log evidence

### `alpha_brain.log` — the 2026-05-09 14:27→14:28 sequence (queue 64bbbb8f → 5c9b12a8)

```
14:27:49.734  APPROVAL_NOTIFY: JARVIS Approval Required — T5
              queue_id 64bbbb8f-...  DELETE /v1/threads/325ff0d2-...
14:28:00.678  APPROVAL_UNLOCK ok — 5-min window started
14:28:02.820  APPROVAL_DECIDE queue_id=64bbbb8f-... decision=approved by=ken
14:28:02.823  100.122.197.119:50424 POST /v1/approvals/64bbbb8f-.../decide 200
14:28:07.688  APPROVAL_NOTIFY: JARVIS Approval Required — T5
              queue_id 5c9b12a8-...  DELETE /v1/threads/325ff0d2-...   ← SAME path
```

Within 5 seconds of approving 64bbbb8f, the same DELETE was retried — but `_get_approved_queue_id` returned None, so the middleware re-queued it as 5c9b12a8 instead of executing+consuming. 5c9b12a8 was never decided and later expired. This is direct evidence the retry happened and the approved row was invisible to the read query.

### Across the full `alpha_brain.log` (1,468 lines matching `approv`)

- Many `APPROVAL_NOTIFY`, `APPROVAL_UNLOCK`, `APPROVAL_DECIDE`, `GET /v1/approvals/pending`.
- **Zero lines mentioning `consume` or `CONSUME`.**

### `postgresql@16.log` — `consume_approved|alpha_approval_queue` grep across full log

- DDL setup of `ENABLE RLS` + `CREATE POLICY approval_queue_isolation` on 2026-05-01.
- GRANTs of `consume_approved_queue_item` to `jarvis_alpha_app`, `jarvis_alpha_writer`.
- INSERTs/UPDATEs from `enqueue_approval_request` and `decide`/`expire` paths (2026-05-07 → 2026-05-08).
- **Zero pg_audit entries for `SELECT public.consume_approved_queue_item(...)`.** The function has never been invoked since the policy was added.

## Section 7 — Hypothesis ranking

| Rank | ID | Hypothesis | Status | Evidence |
|------|----|------------|--------|----------|
| 1 | H5+H1 (caller-side pattern hole) | The caller `_get_approved_queue_id` reads `alpha_approval_queue` on a raw pool conn (user `jarvis_alpha_writer`, no `BYPASSRLS`) without setting `rls.role`. FORCE RLS hides every approved row → returns None → consume never called. The SECDEF function is wired up syntactically but never reached. | **CONFIRMED** | Section 3 (force RLS, writer role lacks bypass) + Section 4 (raw pool.acquire, no `rls.role`) + Section 6 (zero `consume_approved_queue_item` invocations in pg audit log; 14:28 retry got re-queued instead of consumed). |
| 2 | H1 (function-body pattern hole — secondary) | The SECDEF function does not internally `set_config('rls.role','platform_admin', true)`. If the read were fixed but the function still ran on a session without `rls.role`, the function would only succeed because its owner (`jarvisbrain`) is superuser and bypasses FORCE RLS. This works today by accident; it would break if the function were re-owned to a non-superuser. | **LATENT** (not the live cause, but a real pattern hole) | Section 1 (function body has no `set_config`) + Section 2 (owner=jarvisbrain rolsuper=t). |
| 3 | H4 (exception swallowed inside function) | The function body has no exception handler and no `RETURNING`/`IF NOT FOUND` check. A zero-row UPDATE returns silently with no error. | **TRUE BUT MOOT** — function isn't called, so swallowing isn't the live cause; it is, however, the property that would mask any future regression. | Section 1 (no FOUND check). |
| 4 | H6 (DSN role lacks BYPASSRLS) | Pool writer connects as `jarvis_alpha_writer` which has `rolbypassrls=f`. Effectively the underlying mechanism of H5+H1. | (Subsumed in #1.) | Section 3. |
| – | H2 (UPDATE...RETURNING multi-row P0003) | NO. UPDATE has no `RETURNING`, no `INTO` target, no implicit single-row loop. P0003 is impossible here. | RULED OUT | Section 1. |
| – | H3 (Column mismatch / TD-203 lookalike) | NO. `id`, `status`, `executed_at` all exist with matching types; the spec-provided column names `kind` / `error` are wrong per the canonical `\d`, but the function source uses the right ones. | RULED OUT | Section 1 vs `\d alpha_approval_queue` in Section 3. |

## Section 8 — Recommendation

- **Does TD-211 fit the pattern-hole class? YES** — but the pattern hole sits in the **caller** (`brain/middleware/approval.py`'s raw `pool.acquire()` reads/writes of an RLS-forced table without `rls.role`), not in the SECDEF function body. Anchor: Section 6 (zero consume invocations) + Section 4 (caller uses raw `pool.acquire()` instead of `rls_connection()`).
- **Phase 2 fleet write fix vs targeted PR:** If Slab 4 Phase 2 only patches SECDEF function bodies (adding internal `SET LOCAL "rls.role"='platform_admin'`), it will **NOT fix TD-211** — the bug lives in the middleware's read path, which never reaches any SECDEF. TD-211 needs a **targeted pre-Slab-4 PR** that routes `_get_approved_queue_id` and `_consume_approved_queue` through `rls_connection()` (or sets `rls.role` explicitly on the raw conn), AND should still include the function-body internal `rls.role` set as a defense-in-depth fix so the function does not silently depend on its owner being superuser. Verdict: **mixed — targeted fix in the middleware caller, plus a defense-in-depth SECDEF hardening folded into Phase 2.**
