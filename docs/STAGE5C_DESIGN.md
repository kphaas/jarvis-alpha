# STAGE5C_DESIGN.md — Stage 5c Design (Buddy Agent SECDEF + Writer Pool Cutover)

## 1. Objective

Stage 5c flips the `buddy_agent.py` background pool from the read-only `ALPHA_DB_DSN` (currently `jarvis_alpha_app`) to the writer role `jarvis_alpha_writer`, wraps the two remaining naked reads against `alpha_conversation_memory` in `SECURITY DEFINER` functions so the buddy loop can operate cleanly under FORCE RLS without depending on per-session GUC tricks, and removes a stale `set_config('jarvis.current_user', …)` call that no longer has any effect now that the table policy is bypassed by SECDEF wrappers. The result is a buddy loop that needs no RLS GUC plumbing, performs all DB access through SECDEF wrappers or the writer role, and matches the Stage 5a/5b architecture for the FastAPI tier.

---

## 2. Migration Spec

**Filename:** `brain/db/migrations/20260409_130000_buddy_agent_secdef.sql`

Conventions match `20260409_100000_memory_service_secdef.sql`:
- `LANGUAGE plpgsql`
- `SECURITY DEFINER`
- `SET search_path = pg_catalog, public`
- Owner `jarvisbrain`
- `REVOKE EXECUTE … FROM PUBLIC` then explicit `GRANT EXECUTE … TO jarvis_alpha_writer` and `… TO jarvisbrain`
- `SET LOCAL lock_timeout = '2s'`, `SET LOCAL statement_timeout = '10s'` inside the body
- Re-raise list: `integrity_constraint_violation`, `transaction_rollback`, `SQLSTATE '57014'` (query canceled), `SQLSTATE '55P03'` (lock not available); swallow `WHEN OTHERS` with `RAISE WARNING` and a safe sentinel return

### 2.1 `public.list_active_memory_users()`

- **Signature:** `public.list_active_memory_users() RETURNS text[]`
- **Body pseudocode:**
  ```sql
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';
  SELECT COALESCE(array_agg(DISTINCT user_id), ARRAY[]::text[])
    INTO v_users
  FROM public.alpha_conversation_memory
  WHERE user_id IS NOT NULL;
  RETURN v_users;
  ```
- **Exception handling:**
  - Re-raise: `integrity_constraint_violation`, `transaction_rollback`, `SQLSTATE '57014'`, `SQLSTATE '55P03'`
  - `WHEN OTHERS`: `RAISE WARNING 'list_active_memory_users failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE; RETURN ARRAY[]::text[];`
- **Owner / search_path / timeouts:** owned by `jarvisbrain`; `SET search_path = pg_catalog, public`; `lock_timeout = 2s`, `statement_timeout = 10s`
- **REVOKE / GRANT:**
  ```sql
  ALTER FUNCTION public.list_active_memory_users() OWNER TO jarvisbrain;
  REVOKE EXECUTE ON FUNCTION public.list_active_memory_users() FROM PUBLIC;
  GRANT EXECUTE ON FUNCTION public.list_active_memory_users() TO jarvis_alpha_writer;
  GRANT EXECUTE ON FUNCTION public.list_active_memory_users() TO jarvisbrain;
  ```

### 2.2 `public.get_buddy_promotion_candidates(p_user_id text)`

- **Signature:** `public.get_buddy_promotion_candidates(p_user_id TEXT) RETURNS TABLE(id UUID, summary TEXT)`
- **Body pseudocode (replicates buddy_agent.py L156–166 exactly):**
  ```sql
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';
  RETURN QUERY
    SELECT m.id, m.summary
    FROM public.alpha_conversation_memory m
    WHERE m.user_id = p_user_id
      AND m.tier = 'working'
      AND m.created_at < now() - interval '20 hours'
    LIMIT 5;
  ```
- **Exception handling:**
  - Re-raise: `integrity_constraint_violation`, `transaction_rollback`, `SQLSTATE '57014'`, `SQLSTATE '55P03'`
  - `WHEN OTHERS`: `RAISE WARNING 'get_buddy_promotion_candidates failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE; RETURN;`
- **Owner / search_path / timeouts:** owned by `jarvisbrain`; `SET search_path = pg_catalog, public`; `lock_timeout = 2s`, `statement_timeout = 10s`
- **REVOKE / GRANT:**
  ```sql
  ALTER FUNCTION public.get_buddy_promotion_candidates(TEXT) OWNER TO jarvisbrain;
  REVOKE EXECUTE ON FUNCTION public.get_buddy_promotion_candidates(TEXT) FROM PUBLIC;
  GRANT EXECUTE ON FUNCTION public.get_buddy_promotion_candidates(TEXT) TO jarvis_alpha_writer;
  GRANT EXECUTE ON FUNCTION public.get_buddy_promotion_candidates(TEXT) TO jarvisbrain;
  ```

### 2.3 Trailing `COMMENT ON FUNCTION` lines

```sql
COMMENT ON FUNCTION public.list_active_memory_users() IS
  'Stage 5c: SECURITY DEFINER wrapper enumerating distinct memory user_ids for buddy loop.';
COMMENT ON FUNCTION public.get_buddy_promotion_candidates(TEXT) IS
  'Stage 5c: SECURITY DEFINER wrapper returning aging working-tier memories for buddy promotion alerts.';
```

---

## 3. `buddy_agent.py` Refactor Spec

### 3.1 L128 — replace `SELECT DISTINCT` against the table

**Current code (L126–129):**
```python
async with pool.acquire() as conn:
    users = await conn.fetch(
        "SELECT DISTINCT user_id FROM alpha_conversation_memory"
    )
```

**Proposed new code:**
```python
async with pool.acquire() as conn:
    users = await conn.fetch(
        "SELECT unnest(public.list_active_memory_users()) AS user_id"
    )
```

**Justification:** Under FORCE RLS, `jarvis_alpha_writer` cannot read rows from `alpha_conversation_memory` directly without a matching `jarvis.current_user` GUC, and the buddy loop needs the cross-user list. Routing through a SECDEF wrapper bypasses RLS in a controlled, audited way and matches the Stage 5a wrapper pattern. Returning `text[]` and unnesting in SQL keeps the row-shape `users` consumes (`row["user_id"]`) unchanged, so the downstream loop is untouched.

### 3.2 L151–166 — replace naked aging-memory read

**Current code (L151–166):**
```python
async with pool.acquire() as conn:
    await conn.execute(
        "SELECT set_config('jarvis.current_user', $1, true)",
        str(user_id),
    )
    aging = await conn.fetch(
        """
        SELECT id, summary
        FROM alpha_conversation_memory
        WHERE user_id = $1
          AND tier = 'working'
          AND created_at < now() - interval '20 hours'
        LIMIT 5
        """,
        str(user_id),
    )
```

**Proposed new code:**
```python
async with pool.acquire() as conn:
    aging = await conn.fetch(
        "SELECT id, summary FROM public.get_buddy_promotion_candidates($1)",
        str(user_id),
    )
```

**Justification:** The naked SELECT cannot satisfy the table's `alpha_memory_isolation` policy under FORCE RLS as `jarvis_alpha_writer`. The SECDEF wrapper executes as the function owner (`jarvisbrain`) and bypasses RLS for this single, narrowly-scoped query. The wrapper's body is byte-equivalent to the inlined SQL, so call-site semantics are preserved (`row["id"]`, `row["summary"]`, the same `LIMIT 5` cap and 20-hour window).

### 3.3 L153 — remove dead `set_config('jarvis.current_user')` call

**Current code (L152–155):**
```python
await conn.execute(
    "SELECT set_config('jarvis.current_user', $1, true)",
    str(user_id),
)
```

**Proposed new code:** *(deleted entirely — folded into the L151–166 replacement above)*

**Justification:** Becomes dead in this PR — the SECDEF wrapper executes as `jarvisbrain` and ignores the caller's GUC entirely. Removing the call eliminates a misleading line that future readers will assume is load-bearing.

### 3.4 L187 — replace `os.environ.get("ALPHA_DB_DSN")` with config import

**Current code (L184–193):**
```python
async def run_buddy() -> None:
    logger.info("Buddy agent starting — interval %ss", BUDDY_INTERVAL)

    dsn = os.environ.get("ALPHA_DB_DSN")
    if not dsn:
        logger.error("ALPHA_DB_DSN not set — exiting")
        return

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
```

**Proposed new code:**
```python
async def run_buddy() -> None:
    logger.info("Buddy agent starting — interval %ss", BUDDY_INTERVAL)

    from brain.core.config import ALPHA_DB_DSN_BUDDY

    pool = await asyncpg.create_pool(ALPHA_DB_DSN_BUDDY, min_size=1, max_size=3)
```

**Justification:** Centralizes the buddy DSN in `brain/core/config.py` alongside `ALPHA_DB_DSN` and `ALPHA_DB_DSN_WRITER`, lets us flip the pool to `jarvis_alpha_writer` via a secret-file change without code changes, and uses the same fail-fast `os.environ[...]` pattern as the other DSNs (no silent return on missing var). The lazy `from brain.core.config import …` keeps buddy_agent's import surface narrow and avoids loading the rest of the brain config tree at module-import time, which preserves the current LaunchAgent startup characteristics.

---

## 4. Config Changes

### 4.1 `brain/core/config.py`

Add a third DSN line:
```python
ALPHA_DB_DSN_BUDDY: str = os.environ["ALPHA_DB_DSN_BUDDY"]
```
Placed immediately under `ALPHA_DB_DSN_WRITER`. Same fail-fast `os.environ[...]` pattern, no default.

### 4.2 `~/jarvis/.secrets` on Brain (manual step for Ken)

Add a single line:
```
ALPHA_DB_DSN_BUDDY=postgresql://jarvis_alpha_writer:<password>@127.0.0.1:5432/jarvis_alpha
```

The password must be the same secret already used by `ALPHA_DB_DSN_WRITER`. **Ken must add this line manually** — Claude cannot read or write `~/jarvis/.secrets` per CLAUDE.md rules. Ken should verify with `grep ALPHA_DB_DSN_BUDDY ~/jarvis/.secrets` after editing.

---

## 5. LaunchAgent Impact

- **Buddy LaunchAgent restart required.** After the secret is added on Brain, `launchctl kickstart -k gui/<uid>/com.jarvis.alpha.buddy` (or equivalent) is needed for the new env var to be picked up.
- **No plist changes.** `scripts/start_alpha_buddy.sh` already does `set -a; source ~/jarvis/.secrets; set +a` before exec'ing the python module, so any new `ALPHA_DB_DSN_BUDDY=…` line in `~/jarvis/.secrets` is automatically exported into the buddy process environment. The plist itself stays untouched, satisfying the "Never modify deploy scripts" rule (no edit needed).

---

## 6. Smoke Test Plan

**New script:** `scripts/smoke_buddy_secdef.sh`

Each test is one psql command + the expected output shape. Script connects as `jarvis_alpha_writer` to mirror buddy's actual privileges. All five must pass before declaring Stage 5c done.

| # | Test | Command | Expected output |
|---|------|---------|-----------------|
| 1 | `list_active_memory_users` exists and is SECDEF-owned by jarvisbrain | `SELECT proname, prosecdef, proowner::regrole FROM pg_proc WHERE proname = 'list_active_memory_users';` | one row, `prosecdef = t`, `proowner = jarvisbrain` |
| 2 | `get_buddy_promotion_candidates` exists and is SECDEF-owned by jarvisbrain | `SELECT proname, prosecdef, proowner::regrole FROM pg_proc WHERE proname = 'get_buddy_promotion_candidates';` | one row, `prosecdef = t`, `proowner = jarvisbrain` |
| 3 | `jarvis_alpha_writer` can EXECUTE both new functions | `SELECT has_function_privilege('jarvis_alpha_writer', 'public.list_active_memory_users()', 'EXECUTE'), has_function_privilege('jarvis_alpha_writer', 'public.get_buddy_promotion_candidates(text)', 'EXECUTE');` | both `t` |
| 4 | `list_active_memory_users()` returns a non-empty `text[]` whose membership matches a direct `SELECT DISTINCT user_id` run as superuser | `SELECT cardinality(public.list_active_memory_users()) >= 1;` then compare against `SELECT count(DISTINCT user_id) FROM alpha_conversation_memory WHERE user_id IS NOT NULL;` (run as `jarvisbrain`) | `t`; counts must match |
| 5 | `get_buddy_promotion_candidates(<known user_id>)` returns ≤5 rows whose `id`s are a subset of a direct read run as superuser using the same WHERE clause | `SELECT id FROM public.get_buddy_promotion_candidates('<uid>');` then compare to baseline | row count ≤ 5; every returned id present in the baseline set |
| 6 | Naked read from `jarvis_alpha_writer` still blocked by FORCE RLS (regression check) | `SELECT count(*) FROM alpha_conversation_memory;` connected as `jarvis_alpha_writer` with no `jarvis.current_user` set | returns `0` (RLS filters everything) — proves the SECDEF wrappers are the only path |
| 7 | Buddy log shows a clean cycle after restart | `tail -n 50 ~/jarvis-alpha/logs/alpha_buddy.log` after `launchctl kickstart -k …` | one or more `Buddy cycle complete at …` lines, no `Buddy cycle error for user` lines, no `permission denied for table alpha_conversation_memory` |

---

## 7. Rollback Plan

Two-minute revert if buddy starts erroring after Stage 5c lands:

```bash
# 1. On Brain — flip the buddy DSN back to the read-only role.
#    (Ken edits ~/jarvis/.secrets manually and replaces the writer DSN with
#     the same value as ALPHA_DB_DSN, then saves.)
vi ~/jarvis/.secrets
# change ALPHA_DB_DSN_BUDDY=postgresql://jarvis_alpha_writer:...
#     to ALPHA_DB_DSN_BUDDY=postgresql://jarvis_alpha_app:...

# 2. Restart the buddy LaunchAgent so it picks up the reverted DSN.
launchctl kickstart -k gui/$(id -u)/com.jarvis.alpha.buddy

# 3. (Optional, only if functions themselves are suspected) drop the new SECDEF
#    wrappers — safe because nothing else references them yet.
psql -U jarvisbrain -d jarvis_alpha <<'SQL'
DROP FUNCTION IF EXISTS public.get_buddy_promotion_candidates(TEXT);
DROP FUNCTION IF EXISTS public.list_active_memory_users();
SQL

# 4. Revert the buddy_agent.py + config.py edits.
cd ~/jarvis-alpha
git revert <stage-5c-commit-sha>
# (no deploy needed — buddy LaunchAgent will reload on next kickstart)
launchctl kickstart -k gui/$(id -u)/com.jarvis.alpha.buddy

# 5. Verify recovery.
tail -n 20 ~/jarvis-alpha/logs/alpha_buddy.log
```

The DSN flip in step 1 is enough to recover service even before steps 3–4, because reverting to `jarvis_alpha_app` returns buddy to its Stage 5b-era behavior. Steps 3–4 are the cleanup pass.

---

## 8. Risk Assessment

### R1 — `list_active_memory_users()` returns `NULL` instead of an empty array (HIGH)
- **Why it matters:** If `alpha_conversation_memory` is ever empty, `array_agg(DISTINCT user_id)` returns `NULL`, and `unnest(NULL::text[])` produces zero rows — fine — but a downstream `cardinality(NULL)` check or any caller assuming `text[]` non-null would crash.
- **Mitigation:** The function body wraps the aggregate in `COALESCE(..., ARRAY[]::text[])`; the smoke test #1 explicitly checks that `cardinality()` works against a fresh return.

### R2 — Buddy starts erroring on first cycle because `ALPHA_DB_DSN_BUDDY` is missing in `~/jarvis/.secrets` (HIGH)
- **Why it matters:** `brain/core/config.py` uses `os.environ[...]` (fail-fast), so the buddy LaunchAgent will exit at import time with `KeyError: 'ALPHA_DB_DSN_BUDDY'` and respawn-loop.
- **Mitigation:** Phase 3 execution order puts the secret-file edit + verification BEFORE the LaunchAgent kickstart. The verification step (`grep ALPHA_DB_DSN_BUDDY ~/jarvis/.secrets`) is a hard gate. Additionally, Ken keeps the previous buddy build in place — rollback step 1 restores service in under a minute.

### R3 — Forgotten writer GRANTs on the new functions (MEDIUM)
- **Why it matters:** If the migration is run but the `GRANT EXECUTE … TO jarvis_alpha_writer` lines are missing or fail silently, the buddy loop will start, hit the SECDEF call, and get `permission denied for function`.
- **Mitigation:** Smoke test #3 directly checks `has_function_privilege('jarvis_alpha_writer', …, 'EXECUTE')` for both functions. The migration file is reviewed against the Stage 5a template, which already encodes this pattern correctly.

---

## 9. Open Questions

1. **Naming — `ALPHA_DB_DSN_BUDDY` vs reusing `ALPHA_DB_DSN_WRITER`.** The Stage 5b config already exposes `ALPHA_DB_DSN_WRITER`, which points at `jarvis_alpha_writer` — the same role buddy will use. Ken's spec calls for a new `ALPHA_DB_DSN_BUDDY` var. The benefit of a separate var is independent rollback (buddy can be flipped without touching FastAPI) and the option to use a separate connection-pool-sized DSN later. Confirm we want the new var rather than reusing `ALPHA_DB_DSN_WRITER`.
2. **Watchdog and tasks pools.** Stage 5_DISCOVERY listed `brain/agents/watchdog_agent.py` and `brain/tasks/{executor,watchdog}.py` as still using `ALPHA_DB_DSN`/`JARVIS_ALPHA_DB_DSN` (read role). They are explicitly out of Stage 5c scope, but should we open a TD ticket now so the pattern is tracked, or wait until a Stage 5d pass?
3. **TD log entry for `_expire_pending_approvals`.** D1 says it stays as-is and gets logged as TD. Should the TD entry be added in this same PR (e.g., a note in `docs/TD…` or an inline comment in `buddy_agent.py`), or filed separately by Ken?
4. **Smoke script execution role.** Should `scripts/smoke_buddy_secdef.sh` connect as `jarvis_alpha_writer` (mirrors buddy's runtime) or as `jarvisbrain` (full visibility for the baseline-comparison tests)? Current draft uses `jarvis_alpha_writer` for tests 1–6 and `jarvisbrain` for the baseline diffs in tests 4–5. Confirm the split is acceptable.

---

## 10. Phase 3 Execution Order

Numbered sequence. Each step has a verification gate; do not advance until the gate passes.

1. **Create branch.** `git checkout -b claude/stage-5c-20260409` from `main`.
   - Verify: `git status` shows clean working tree on the new branch.
2. **Write migration file.** Create `brain/db/migrations/20260409_130000_buddy_agent_secdef.sql` per §2.
   - Verify: file exists; `grep -c "CREATE OR REPLACE FUNCTION" brain/db/migrations/20260409_130000_buddy_agent_secdef.sql` returns `2`.
3. **Edit `brain/core/config.py`.** Add `ALPHA_DB_DSN_BUDDY` line per §4.1.
   - Verify: `python -c "import os; os.environ['ALPHA_DB_DSN']='x'; os.environ['ALPHA_DB_DSN_WRITER']='x'; os.environ['ALPHA_DB_DSN_BUDDY']='x'; os.environ['ALPHA_GATEWAY_URL']='x'; from brain.core import config; print(config.ALPHA_DB_DSN_BUDDY)"` prints `x`.
4. **Edit `brain/agents/buddy_agent.py`.** Apply §3.1, §3.2, §3.3, §3.4 in that order.
   - Verify: `ruff check brain/agents/buddy_agent.py` passes.
   - Verify: `grep -c "set_config" brain/agents/buddy_agent.py` returns `0`.
   - Verify: `grep -c "list_active_memory_users\|get_buddy_promotion_candidates" brain/agents/buddy_agent.py` returns `2`.
5. **Write smoke script.** Create `scripts/smoke_buddy_secdef.sh` per §6.
   - Verify: `bash -n scripts/smoke_buddy_secdef.sh` parses cleanly; `chmod +x` it.
6. **Local lint sweep on every changed Python file.** `ruff check brain/agents/buddy_agent.py brain/core/config.py`.
   - Verify: zero findings.
7. **Commit (Phase 3 only — wait for Ken's review of this design first).** `git add` the four files; commit with message `feat(stage-5c): buddy SECDEF wrappers + writer pool cutover`.
   - Verify: `git log -1 --stat` lists exactly: migration, `buddy_agent.py`, `config.py`, `smoke_buddy_secdef.sh`.
8. **Push branch and stop.** `git push -u origin claude/stage-5c-20260409`. **Do not merge.** Hand off to Ken for review.
9. **(After Ken merges)** On Brain, Ken adds `ALPHA_DB_DSN_BUDDY=…` to `~/jarvis/.secrets`.
   - Verify (Ken runs): `grep -c ALPHA_DB_DSN_BUDDY ~/jarvis/.secrets` returns `1`.
10. **(After Ken merges)** Ken applies the migration on Brain: `psql -U jarvisbrain -d jarvis_alpha -f brain/db/migrations/20260409_130000_buddy_agent_secdef.sql`.
    - Verify (Ken runs): smoke tests #1, #2, #3 from §6.
11. **(After Ken merges)** Ken kickstarts the buddy LaunchAgent: `launchctl kickstart -k gui/$(id -u)/com.jarvis.alpha.buddy`.
    - Verify (Ken runs): smoke tests #4, #5, #6, #7 from §6 (in order).
12. **(After Ken merges)** 24-hour observation window — `tail -F ~/jarvis-alpha/logs/alpha_buddy.log` for any `Buddy cycle error` lines.
    - Verify: zero error lines over the window. If any appear, execute §7 rollback immediately.

---
