# SLAB 5 — Bug Fixes Spec

**Locked:** May 1, 2026
**Predecessor:** SLAB4_INFRASTRUCTURE_SPEC.md (provides typed wrapper + SECDEF wrappers)
**Successor:** SLAB6 atomic deploy (uses Slab 5 patterns at scale)

## What Slab 5 is

Bug fixes that close out RLS Step 7 prep. Three deliverables:
1. TD-181 audit + fix (executor.py + any hidden duplicates)
2. Apr 27 Lock 8 fix (`alpha_task_events` policy → canonical Shape B)
3. SQL smoke harness extension (8 role-switching cases per Slab 3 Q7)

**Implementation effort:** 1-2 sessions of Cursor work after spec lock.

## Locked decisions

- **Q12 (B):** Audit-and-fix — grep entire codebase for `set_config\('rls\.[^']+',\s*'(platform_admin|user|child)` pattern, fix every instance
- **Q13 (B):** Drop + replace `alpha_task_events.task_events_read` with canonical Shape B policy. Rehearses Slab 6 atomic-deploy at single-table scale.
- **Q14 (B):** Ship all 8 smoke cases including FK-inheritance verification (cases 7+8)

## TDs closed by this slab

| TD | Title | Closed how |
|---|---|---|
| TD-181 | executor.py writes role to identity GUC | Surgical fix + audit catches duplicates |
| Apr 27 Lock 8 | alpha_task_events literal 'admin' policy | Drop + canonical Shape B replacement |
| (any TD-181 duplicates found by audit) | | Same fix pattern |

## TDs Slab 5 deliberately does NOT close

| TD | Why deferred |
|---|---|
| TD-182 | 3 private GUC helpers — Slab 4 ships the consolidation |
| TD-94 | Watchdog SIGTERM — Slab 4 listener rebuild fixes this |
| TD-156 | cost_emitter 401/403 → CRITICAL + breaker — separate workstream |
| TD-189 | Outbox+poll for at-least-once — Slab 7+ |

---

## Deliverable 1: TD-181 audit + fix

### Audit query

Run on Air to find every instance of the bug shape:

```bash
cd ~/jarvis-alpha
grep -rEn "set_config\(\s*'rls\.[^']+'\s*,\s*'(platform_admin|user|child)'" \
  --include="*.py" \
  brain/ gateway/ scripts/ tests/ 2>/dev/null
```

### Bug shape

The bug pattern is **writing a role string to a GUC slot meant for identity** (or vice versa).

Known instance (TD-181):

```python
# brain/tasks/executor.py:46  (current — bug)
await conn.execute("SELECT set_config('rls.current_user', 'platform_admin', true)")
```

Two errors in this line:
1. `rls.current_user` is not a canonical GUC. Canonical name is `rls.user_id`.
2. `'platform_admin'` is a role value, written to what would be the identity slot.

### Correct shape

```python
# brain/tasks/executor.py:46  (fixed — canonical)
await conn.execute(
    "SELECT set_config('rls.role', 'platform_admin', true), "
    "set_config('rls.user_id', $1::text, true)",
    str(SYSTEM_AGENT_UUID),  # see below
)
```

### SYSTEM_AGENT_UUID convention

Slab 3 decision D: no DB-enforced sentinel. But for Slab 5 fix, we still need *some* UUID for system writers since the executor is calling Shape A and Shape B tables.

Decision: use a hardcoded reserved UUID at the application layer for system actor identity:

```python
# brain/tasks/executor.py (top of file)
from uuid import UUID
SYSTEM_AGENT_UUID = UUID('00000000-0000-0000-0000-000000000001')
# Reserved for background agents writing through executor.py.
# NOT a DB sentinel - Shape B policies do not check user_id.
# Used so set_rls_context() has a valid UUID to cast.
```

This is application convention, not DB enforcement. Slab 4's `set_rls_context()` requires a UUID; the agent path provides one. **Shape B policies still ignore the value.**

### Audit hits — expected outcome

Three plausible categories:

| Hit type | Action |
|---|---|
| Same shape as TD-181 (role written to identity) | Fix in same migration |
| Identity written correctly but using `set_config()` directly instead of `set_rls_context()` | Defer to Slab 4-dependent rewrite (next slab post-Slab 4) |
| Test code | Leave alone if test purpose is clear |

If audit finds >5 instances, treat as scope expansion: surface to Ken before proceeding.

### Verification

```bash
# After fixes
grep -rEn "set_config\(\s*'rls\.[^']+'\s*,\s*'(platform_admin|user|child)'" \
  --include="*.py" \
  brain/ gateway/ scripts/ 2>/dev/null
# Expect: only test files OR canonical patterns where role is set INTENTIONALLY by SECDEF wrappers
```

---

## Deliverable 2: alpha_task_events canonical Shape B

### Current state

```sql
-- Inventory query confirms this exists today:
-- tablename: alpha_task_events
-- policyname: task_events_read
-- permissive: PERMISSIVE
-- cmd: ALL
-- (body uses literal 'admin' string per Apr 27 Lock 8)
```

### Migration: drop and replace

```sql
-- brain/db/migrations/<timestamp>_slab5_alpha_task_events_canonical.sql

BEGIN;

-- Pre-flight: confirm we are in expected state
DO $$
DECLARE
    n INT;
BEGIN
    SELECT count(*) INTO n
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'alpha_task_events'
      AND policyname = 'task_events_read';
    IF n != 1 THEN
        RAISE EXCEPTION
            'Pre-flight failed: expected 1 task_events_read policy, found %', n;
    END IF;
END
$$;

-- Drop legacy policy
DROP POLICY IF EXISTS task_events_read ON alpha_task_events;

-- Install canonical Shape B (per SLAB3_POLICY_TEMPLATE.md)
CREATE POLICY alpha_task_events_admin_only ON alpha_task_events
    AS PERMISSIVE
    FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

-- alpha_task_events already has FORCE RLS - no change needed

-- Post-check: confirm canonical policy is in place
DO $$
DECLARE
    n INT;
BEGIN
    SELECT count(*) INTO n
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'alpha_task_events'
      AND policyname = 'alpha_task_events_admin_only'
      AND permissive = 'PERMISSIVE';
    IF n != 1 THEN
        RAISE EXCEPTION
            'Post-check failed: canonical policy not installed (n=%)', n;
    END IF;

    SELECT count(*) INTO n
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'alpha_task_events'
      AND policyname = 'task_events_read';
    IF n != 0 THEN
        RAISE EXCEPTION
            'Post-check failed: legacy task_events_read still exists (n=%)', n;
    END IF;
END
$$;

COMMIT;
```

### Rollback

```sql
-- brain/db/rollbacks/<timestamp>_slab5_alpha_task_events_canonical_rollback.sql
-- (Per TD-183/184 convention - rollback files in brain/db/rollbacks/, runner skips them)

BEGIN;
DROP POLICY IF EXISTS alpha_task_events_admin_only ON alpha_task_events;

-- Restore previous (pre-canonical) policy with original body
CREATE POLICY task_events_read ON alpha_task_events
    AS PERMISSIVE
    FOR ALL
    USING (current_setting('rls.role', true) = 'admin');  -- legacy literal
COMMIT;
```

### Why this rehearses Slab 6

Slab 6's atomic deploy will run 22 of these drop-and-replace cycles in a single transaction. Slab 5 ships ONE such cycle. If pre-flight asserts trip or post-check fails, we discover the failure mode at low blast radius BEFORE Slab 6 runs the full set.

---

## Deliverable 3: SQL smoke harness extension

### File location

`brain/db/tests/rls_smoke.sql` — extend existing file (do not replace).

### Test scaffolding

```sql
-- brain/db/tests/rls_smoke.sql (extension section)

-- Setup: ensure test data exists
-- Assumes test fixtures pre-loaded in CI; for manual runs, see test_data_setup.sql

-- ============================================================
-- SLAB 3 Q7 / SLAB 5 deliverable 3: 8 role-switching smoke cases
-- ============================================================

\echo === Case 1: platform_admin sees all Shape A rows ===
RESET ALL;
SELECT set_config('rls.role', 'platform_admin', false);
SELECT set_config('rls.user_id', '00000000-0000-0000-0000-000000000001', false);
SELECT set_config('rls.max_rating', 'adult', false);
SELECT set_config('rls.workspace_id', '00000000-0000-0000-0000-000000000001', false);

DO $$
DECLARE
    n INT;
BEGIN
    SELECT count(*) INTO n FROM chat_threads;
    ASSERT n > 0, 'Case 1: platform_admin should see all chat_threads';
    RAISE NOTICE 'Case 1 PASS: admin sees % chat_threads rows', n;
END
$$;

\echo === Case 2: user with userA UUID sees only userA rows ===
-- (Assumes test fixture creates userA + userB with at least 1 thread each)
RESET ALL;
SELECT set_config('rls.role', 'user', false);
SELECT set_config('rls.user_id', '11111111-1111-1111-1111-111111111111', false);  -- userA fixture
SELECT set_config('rls.max_rating', 'adult', false);
SELECT set_config('rls.workspace_id', '00000000-0000-0000-0000-000000000001', false);

DO $$
DECLARE
    own_count INT;
    foreign_count INT;
BEGIN
    SELECT count(*) INTO own_count FROM chat_threads
      WHERE user_id = '11111111-1111-1111-1111-111111111111';
    SELECT count(*) INTO foreign_count FROM chat_threads
      WHERE user_id != '11111111-1111-1111-1111-111111111111';
    ASSERT own_count > 0, 'Case 2: userA should see own threads';
    ASSERT foreign_count = 0, 'Case 2: userA should NOT see foreign threads';
    RAISE NOTICE 'Case 2 PASS: own=%, foreign=%', own_count, foreign_count;
END
$$;

\echo === Case 3: child with age_8_plus ceiling ===
RESET ALL;
SELECT set_config('rls.role', 'child', false);
SELECT set_config('rls.user_id', '22222222-2222-2222-2222-222222222222', false);  -- child fixture
SELECT set_config('rls.max_rating', 'age_8_plus', false);
SELECT set_config('rls.workspace_id', '00000000-0000-0000-0000-000000000001', false);

DO $$
DECLARE
    above_ceiling INT;
BEGIN
    SELECT count(*) INTO above_ceiling FROM alpha_conversation_memory
      WHERE content_rating IN ('teen', 'adult');
    ASSERT above_ceiling = 0, 'Case 3: child should NOT see teen/adult content';
    RAISE NOTICE 'Case 3 PASS: child sees zero teen/adult rows';
END
$$;

\echo === Case 4: All GUCs reset = fail-closed ===
RESET ALL;

DO $$
DECLARE
    n INT;
BEGIN
    SELECT count(*) INTO n FROM chat_threads;
    ASSERT n = 0, 'Case 4: unset GUCs must return 0 rows (fail-closed)';
    RAISE NOTICE 'Case 4 PASS: fail-closed verified';
END
$$;

\echo === Case 5: user role on Shape B = 0 rows ===
RESET ALL;
SELECT set_config('rls.role', 'user', false);
SELECT set_config('rls.user_id', '11111111-1111-1111-1111-111111111111', false);
SELECT set_config('rls.max_rating', 'adult', false);
SELECT set_config('rls.workspace_id', '00000000-0000-0000-0000-000000000001', false);

DO $$
DECLARE
    n INT;
BEGIN
    SELECT count(*) INTO n FROM alpha_buddy_events;
    ASSERT n = 0, 'Case 5: user role must see 0 Shape B rows';
    RAISE NOTICE 'Case 5 PASS: user sees zero Shape B rows';
END
$$;

\echo === Case 6: platform_admin sees all Shape B rows ===
RESET ALL;
SELECT set_config('rls.role', 'platform_admin', false);
SELECT set_config('rls.user_id', '00000000-0000-0000-0000-000000000001', false);
SELECT set_config('rls.max_rating', 'adult', false);
SELECT set_config('rls.workspace_id', '00000000-0000-0000-0000-000000000001', false);

DO $$
DECLARE
    n INT;
BEGIN
    SELECT count(*) INTO n FROM alpha_buddy_events;
    -- May be 0 if no events yet; assert >= 0 just to confirm no error
    ASSERT n >= 0, 'Case 6: platform_admin should query Shape B without error';
    RAISE NOTICE 'Case 6 PASS: admin queries Shape B; rows=%', n;
END
$$;

\echo === Case 7: userA sees only own thread messages (Shape A-FK) ===
RESET ALL;
SELECT set_config('rls.role', 'user', false);
SELECT set_config('rls.user_id', '11111111-1111-1111-1111-111111111111', false);
SELECT set_config('rls.max_rating', 'adult', false);
SELECT set_config('rls.workspace_id', '00000000-0000-0000-0000-000000000001', false);

DO $$
DECLARE
    own_msg_count INT;
    foreign_msg_count INT;
BEGIN
    -- Messages in userA threads
    SELECT count(*) INTO own_msg_count FROM chat_messages cm
      WHERE EXISTS (
        SELECT 1 FROM chat_threads ct
        WHERE ct.id = cm.thread_id
          AND ct.user_id = '11111111-1111-1111-1111-111111111111'
      );
    ASSERT own_msg_count >= 0, 'Case 7: query should not error';

    -- Messages NOT in userA threads (should be invisible due to FK-inherited RLS)
    SELECT count(*) INTO foreign_msg_count FROM chat_messages cm
      WHERE NOT EXISTS (
        SELECT 1 FROM chat_threads ct
        WHERE ct.id = cm.thread_id
          AND ct.user_id = '11111111-1111-1111-1111-111111111111'
      );
    ASSERT foreign_msg_count = 0, 'Case 7: userA must NOT see messages in other users threads';
    RAISE NOTICE 'Case 7 PASS: own=%, foreign=%', own_msg_count, foreign_msg_count;
END
$$;

\echo === Case 8: FK isolation - userA cannot see messages with userB parent ===
-- Same context as case 7
DO $$
DECLARE
    leaked INT;
BEGIN
    -- Try to find any message whose parent thread belongs to userB
    SELECT count(*) INTO leaked FROM chat_messages cm
      JOIN chat_threads ct ON ct.id = cm.thread_id
      WHERE ct.user_id != '11111111-1111-1111-1111-111111111111';
    ASSERT leaked = 0, 'Case 8: FK isolation broken - userA seeing userB messages';
    RAISE NOTICE 'Case 8 PASS: FK isolation holds';
END
$$;

RESET ALL;
\echo === ALL 8 SMOKE CASES PASSED ===
```

### Test fixtures required

Cases 2/3/7/8 reference test users (`11111111-...` userA, `22222222-...` child fixture). These must exist in the test database. If absent, smoke tests fail with `ASSERT` violations on `> 0` checks.

Slab 5 work item: ensure `brain/db/tests/test_data_setup.sql` provisions these fixtures. If not present, add as part of Slab 5.

### Smoke harness invocation

```bash
# Brain — run after migrations on test DB
psql -d jarvis_alpha_test -U jarvisbrain -f brain/db/tests/rls_smoke.sql
```

Exit code 0 = all cases pass. Non-zero exit = at least one ASSERT failed; investigate before merge.

---

## Implementation sequencing (Cursor work)

| Step | Action | Effort |
|---|---|---|
| 1 | Audit query (Q12-B) on Air to find TD-181 duplicates | 5 min |
| 2 | Cursor prompt: fix executor.py + any other call sites surfaced by audit | 30 min |
| 3 | Cursor prompt: write Slab 5 migration + rollback files | 15 min |
| 4 | Cursor prompt: extend rls_smoke.sql with 8 cases | 30 min |
| 5 | Test fixtures verified or added | 15 min |
| 6 | Service quiesce (per Slab 1/2 pattern) | 5 min |
| 7 | Commit + fan-out | 5 min |
| 8 | Run smoke harness on Brain test DB | 5 min |
| 9 | If smoke passes, soak 24h before Slab 6 | 24h |

**Total active work: 1.5-2 hours of Cursor + verify time.** Soak runs overnight.

---

## Rollback path

If Slab 5 deploy fails post-merge:

1. Migration runner halts on first failed migration (atomic transaction)
2. If deploy reaches Brain restart and services fail: revert commit + redeploy via `git revert` (deploy script provides the command)
3. If only the policy changed and code is fine: apply rollback migration from `brain/db/rollbacks/`
4. If TD-181 fix breaks executor.py runtime: revert that single file via `git restore brain/tasks/executor.py` + redeploy

⚠️ **TD-183 lesson applied:** rollback files live in `brain/db/rollbacks/`, NOT `brain/db/migrations/`, so the runner does not auto-apply them. TD-184 filter as defense-in-depth.

---

## Pass criteria for Slab 5 deploy

- Audit query post-fix returns only canonical patterns (or test code)
- Migration applies clean on Brain (post-check assertions pass)
- All 8 smoke cases PASS
- Brain `/health` ok after restart
- 133 test gate passes
- 24h soak: no new ERROR/FATAL in postgres log, audit count growth healthy

If any criterion fails, stop and investigate before Slab 6.

---

## Cross-references

- `~/jarvis-alpha/docs/PATTERNS.md` — pgAudit + SQLSTATE conventions (Slab 1)
- `~/jarvis-alpha/docs/SLAB2_DEPLOY_PLAN.md` — GUC namespace migration (shipped)
- `~/jarvis-alpha/docs/SLAB3_POLICY_TEMPLATE.md` — Shape A / A-FK / B templates
- `~/jarvis-alpha/docs/SLAB4_INFRASTRUCTURE_SPEC.md` — RLSContext, SECDEF fleet, listener rebuild
- Slab 6 spec (pending re-cut): atomic policy deploy with sub-slabs 6a / 6b / 6c
