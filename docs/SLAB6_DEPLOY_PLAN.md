# SLAB 6 — Atomic Policy Deploy Plan

**Locked:** May 1, 2026
**Predecessors:** SLAB3_POLICY_TEMPLATE.md, SLAB4_INFRASTRUCTURE_SPEC.md, SLAB5_BUG_FIXES_SPEC.md
**Outside review:** Perplexity audit (4 refinements integrated)

## What Slab 6 ships

Atomic rewrite of all 22 production RLS policies to canonical Shape A / A-FK / B templates from Slab 3, plus RLS enablement on 3 new tables.

## Sub-slab structure

| Sub-slab | Scope | Priority |
|---|---|---|
| 6a | Rewrite 22 existing RLS policies to canonical templates | P0 |
| 6b | Add RLS to vault_document_permissions (CRITICAL — TD-161) | P0 next session |
| 6c | Add RLS to alpha_workspace_users + jarvis_request_log | P1 |

24h soak between each sub-slab. **6a ships first.** This doc covers 6a; 6b/6c get sibling docs after 6a soaks clean.

## Locked decisions

- **Q16 (A):** Sequential 6a → 6b → 6c with soak between
- **Q17 (A):** Audit + rewrite same slab; Step 0 reads pg_policies
- **Q18 (A'):** Single transaction + lock_timeout 5s + statement_timeout 30s + advisory_xact_lock
- **Q19 (A'):** pg_dump --schema-only --acls --no-owner pre-flight + RAISE NOTICE forensic + static rollback
- **Perplexity refinements:** pg_locks pre-check, staging dry run on jarvis_alpha_test, post-deploy verify

## TDs closed by 6a

| TD | Title |
|---|---|
| TD-193 | All 22 policies audited + rewritten to canonical |
| TD-196 | chat_threads_isolation gets admin override |
| Apr 27 verify items | All 6 flagged tables resolved (alpha_buddy_events, vault_access_log, alpha_dream_sessions, alpha_task_graphs RESTRICTIVE, alpha_watchdog_events 2-policy, vault_documents 2-policy) |

## TDs Slab 6a deliberately defers

| TD | Why |
|---|---|
| TD-161 | Sub-slab 6b/6c handle the 3 RLS-off tables |
| TD-194 | CHECK constraint on alpha_users.role — separate slab |
| TD-195 | run_smoke.sh psql path parameterization — cosmetic |

---

## 6a deploy sequence

### Step -1 — Advisory lock collision check (pre-flight, READ-ONLY)

```sql
-- Run on Brain
SELECT * FROM pg_locks
WHERE locktype = 'advisory'
  AND objid = 2026050101;
-- Expect: 0 rows. If any rows, abort and investigate.
```

### Step 0 — Policy audit (READ-ONLY)

```sql
-- Capture EXACT current policy bodies for spec input + rollback reference
\copy (
  SELECT tablename, policyname, permissive, cmd, qual, with_check
  FROM pg_policies
  WHERE schemaname = 'public'
  ORDER BY tablename, policyname
) TO '/tmp/slab6a_policies_pre_<ts>.csv' WITH CSV HEADER;
```

Output drives the rewrite migration body. Any surprising policy texts get flagged + investigated before proceeding.

### Step 1 — pg_dump pre-flight (battle-tested rollback artifact)

```bash
# Brain — captures policies + ACLs in canonical Postgres format
pg_dump --schema-only --acls --no-owner \
  -t 'alpha_*' -t 'chat_*' -t 'vault_*' \
  jarvis_alpha > /tmp/slab6a_predump_<ts>.sql
```

This file is the canonical rollback artifact. If anything goes catastrophically wrong, replay it.

### Step 2 — Staging dry run on jarvis_alpha_test

Run the full migration against `jarvis_alpha_test` first. Time the transaction. Verify post-state matches spec.

```bash
# Brain — Run the migration against test DB, time it, capture pg_locks during
time /opt/homebrew/Cellar/postgresql@16/16.13/bin/psql \
  -d jarvis_alpha_test \
  -U jarvisbrain \
  -v ON_ERROR_STOP=1 \
  -f brain/db/migrations/<TS>_slab6a_canonical_policies.sql

# Then run smoke harness to verify
bash scripts/run_smoke.sh test
```

Expect: transaction completes in <10s, smoke harness passes all 8 cases (Case 1 should now pass since chat_threads gets admin override).

### Step 3 — Service quiesce (Slab 1/2 pattern)

```bash
# Brain — bootout services in dep order (reverse-restart order)
launchctl bootout gui/$(id -u) com.jarvis.alpha.buddy
launchctl bootout gui/$(id -u) com.jarvis.alpha.executor
launchctl bootout gui/$(id -u) com.jarvis.alpha.brain
# Verify drained
psql -d jarvis_alpha -U jarvisbrain -c \
  "SELECT count(*) FROM pg_stat_activity WHERE datname='jarvis_alpha' AND state != 'idle';"
# Expect: only psql connection itself
```

### Step 4 — Atomic deploy

Single transaction with safety rails. Migration file shape:

```sql
-- brain/db/migrations/<TS>_slab6a_canonical_policies.sql

BEGIN;

-- Concurrency rails
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(2026050101);

-- Pre-flight: confirm we are in expected pre-Slab-6a state
DO $$
DECLARE
    n INT;
BEGIN
    SELECT count(*) INTO n FROM pg_policies WHERE schemaname='public';
    IF n < 25 OR n > 35 THEN
        RAISE EXCEPTION 'Pre-flight failed: unexpected policy count (%)', n;
    END IF;
    RAISE NOTICE 'Pre-flight OK: % policies present', n;
END $$;

-- Forensic: dump current bodies into deploy log
DO $$
DECLARE
    r RECORD;
BEGIN
    RAISE NOTICE '=== SLAB 6A — pre-rewrite policy snapshot ===';
    FOR r IN
        SELECT tablename, policyname, permissive, qual
        FROM pg_policies
        WHERE schemaname='public'
        ORDER BY tablename, policyname
    LOOP
        RAISE NOTICE 'pre: % / % (%) USING: %',
            r.tablename, r.policyname, r.permissive, r.qual;
    END LOOP;
END $$;

-- ============================================================
-- 22 × DROP POLICY + 22 × CREATE POLICY
-- ============================================================
-- Generated from Step 0 audit + Slab 3 templates
-- Order: Shape A first, then Shape A-FK, then Shape B
-- ============================================================

-- chat_threads (Shape A + child overlay)
DROP POLICY IF EXISTS chat_threads_isolation ON chat_threads;
DROP POLICY IF EXISTS child_profile_scope ON chat_threads;
CREATE POLICY chat_threads_user_or_admin ON chat_threads
  AS PERMISSIVE FOR ALL
  USING (
    current_setting('rls.role', true) = 'platform_admin'
    OR user_id = current_setting('rls.user_id', true)
  )
  WITH CHECK (
    current_setting('rls.role', true) = 'platform_admin'
    OR user_id = current_setting('rls.user_id', true)
  );
CREATE POLICY chat_threads_child_rating_ceiling ON chat_threads
  AS RESTRICTIVE FOR SELECT
  USING (
    current_setting('rls.role', true) <> 'child'
    OR rating_ceiling_check(content_rating, current_setting('rls.max_rating', true))
  );

-- alpha_conversation_memory (Shape A + child overlay)
-- ... full 22-policy block populated from Step 0 ...

-- chat_messages (Shape A-FK)
-- alpha_task_events stays canonical (Slab 5 already shipped this)
-- ... etc ...

-- ============================================================
-- Post-check: verify 22 canonical policies, no legacy left behind
-- ============================================================
DO $$
DECLARE
    legacy_count INT;
    canonical_count INT;
BEGIN
    -- No policies with literal 'admin' (non-canonical)
    SELECT count(*) INTO legacy_count FROM pg_policies
    WHERE schemaname='public' AND qual LIKE '%''admin''%';
    IF legacy_count > 0 THEN
        RAISE EXCEPTION 'Post-check failed: % policies still use legacy admin literal', legacy_count;
    END IF;

    -- All RLS tables have at least one PERMISSIVE policy (Q6 invariant)
    SELECT count(*) INTO canonical_count FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname='public' AND c.relrowsecurity=true
      AND NOT EXISTS (
        SELECT 1 FROM pg_policies p
        WHERE p.schemaname='public' AND p.tablename=c.relname
          AND p.permissive='PERMISSIVE'
      );
    IF canonical_count > 0 THEN
        RAISE EXCEPTION 'Post-check failed: % RLS tables missing PERMISSIVE policy', canonical_count;
    END IF;

    RAISE NOTICE 'Post-check OK: zero legacy literals, Q6 invariant holds';
END $$;

COMMIT;
```

### Step 5 — Post-deploy verification

```sql
-- Brain — query live state, confirm canonical
SELECT tablename, count(*) AS policy_count,
       count(*) FILTER (WHERE permissive='PERMISSIVE') AS perm,
       count(*) FILTER (WHERE permissive='RESTRICTIVE') AS rest
FROM pg_policies
WHERE schemaname='public'
GROUP BY tablename
ORDER BY tablename;
```

Then run smoke harness against PROD (read-only assertions) — but this needs a smoke fixture in prod, OR re-run staging smoke as the canonical correctness signal.

### Step 6 — Service restart (reverse dep order)

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jarvis.alpha.brain.plist
# verify health
curl -ks https://jarvis-brain.tail40ed36.ts.net:8186/health
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jarvis.alpha.executor.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jarvis.alpha.buddy.plist
```

### Step 7 — 24h soak

Watch:
- pgAudit log growth (should continue normally)
- Brain test gate (133 tests should still pass)
- No new ERROR/FATAL in postgres log
- Buddy + Watchdog still healthy
- Application traffic patterns unchanged (no users locked out by overly-strict policy)

If any signal red within 24h: apply rollback file from `brain/db/rollbacks/<TS>_slab6a_canonical_policies_rollback.sql`.

---

## Rollback file shape

`brain/db/rollbacks/<TS>_slab6a_canonical_policies_rollback.sql` — drops all 22 canonical, recreates the EXACT pre-Slab-6a bodies (captured from Step 0 audit).

Lives in `brain/db/rollbacks/` — outside migration runner scan path (TD-183 lesson, TD-184 filter as defense-in-depth).

---

## Pass criteria

| Criterion | Where |
|---|---|
| Step 0 audit captures all current bodies | CSV file exists |
| Step 1 pg_dump succeeds | dump file exists, valid SQL |
| Step 2 staging dry run | tx <10s, smoke harness 8/8 |
| Step 4 atomic deploy on prod | 0 errors, 0 warnings, all DOs print OK |
| Step 5 post-deploy verify | zero legacy literals, all canonical |
| Step 6 services healthy | /health 200, test gate 133/133 |
| Step 7 24h soak | clean logs, no application complaints |

If any step fails, halt and apply rollback file. Don't continue to next step.

---

## Cursor work breakdown

| Step | Cursor task |
|---|---|
| Spec finalize | Generate full migration body from Step 0 audit |
| Migration write | Cursor prompt with all 22 policies inline |
| Rollback write | Cursor prompt with pre-state restore |
| Test on jarvis_alpha_test | Local Brain command |
| Production deploy | Use `bash scripts/jarvisalpha_commit.sh` (existing pipeline) |

Implementation is ~2-3 hours of Cursor work + 24h soak.

---

## Cross-references

- `~/jarvis-alpha/docs/SLAB3_POLICY_TEMPLATE.md` — Shape A / A-FK / B canonical templates
- `~/jarvis-alpha/docs/SLAB4_INFRASTRUCTURE_SPEC.md` — RLSContext + SECDEF fleet (rating_ceiling_check)
- `~/jarvis-alpha/docs/SLAB5_BUG_FIXES_SPEC.md` — TD-181 + alpha_task_events rehearsal
- `~/jarvis-alpha/scripts/run_smoke.sh` — smoke harness for staging dry run
- `~/jarvis-alpha/brain/db/tests/rls_smoke.sql` — 8 cases, all should PASS post-Slab-6a
- TD-183 / TD-184 — rollback file location convention + runner filter

---

## REVISION — 2026-05-07 — Scope Locked at 9 Policies

**Source:** Live `pg_policies` audit on prod (`jarvis_alpha`), 2026-05-07.
**Outcome:** Original "atomic 22-policy" framing replaced with verified 9-policy
locked scope. Remaining items deferred to Slab 4 and Slab 6b with traceability.

### Final 9-policy scope (single transaction)

| # | Policy | Change |
|---|---|---|
| 1 | `chat_threads_isolation` | Add admin override (Shape A canonical) — closes TD-196 |
| 2 | `chat_messages_isolation` | Add admin override (Shape A-FK canonical) — closes new finding |
| 3 | `alpha_memory_isolation` | Add explicit `with_check` clause |
| 4 | `semantic_isolation` | Add explicit `with_check` clause |
| 5 | `task_graph_isolation` | Add explicit `with_check` clause |
| 6 | `task_step_isolation` | Add explicit `with_check` clause |
| 7 | `vault_access_log_admin` | Add explicit `with_check` clause |
| 8 | `vault_documents_write` | Add explicit `with_check` clause |
| 9 | `vault_pipeline_admin` | Add explicit `with_check` clause |

### Deferred from 6a

| Item | Owner | Why deferred |
|---|---|---|
| `watchdog_events_read` (`qual=true`) | **Slab 4** (TD-197) | Canonical fix is `record_watchdog_event()` SECDEF function from Slab 4 fleet. Doing raw Shape B in 6a would break the watchdog process (no `rls.role` set today) and create rework. |
| `watchdog_events_system_write` (`with_check=true`) | **Slab 4** (TD-197) | Same reason — SECDEF wrapper is the canonical big-tech pattern. |
| Over-broad `arwd` grants on `alpha_watchdog_events` to `jarvis_alpha_app` + `jarvis_alpha_writer` | **Slab 7c** | REVOKE replaces with EXECUTE on SECDEF function only. |
| `vault_documents_read` (custom classification logic) | **Slab 6b** | Vault sub-slab. Either formalize as Shape C or refactor to Shape B + view layer. |

### Audit findings reference

- 29 policies / 22 tables surveyed
- Bug class instances: 5 total (TD-181, Apr 27 Lock 8, TD-196, chat_messages, watchdog × 2)
- Defect rate on policy correctness: ~23% (5 of 22 tables had a role/identity/admin-override bug)
- See: live audit output `/tmp/rls_audit_20260507_170959.txt`

### Smoke harness additions for staging dry-run

Cases 9 and 10 added to `brain/db/tests/rls_smoke.sql`:
- **Case 9** — chat_messages admin override READ
- **Case 10** — chat_messages admin override WRITE

All 10 cases must PASS on `jarvis_alpha_test` before prod deploy.

### Pre-flight checks completed (2026-05-07)

- **R4** chat_messages admin consumer audit: zero current callers using admin context. Slab 6a fix adds capability rather than restoring break. Low risk.
- **R5** watchdog grants + RLS context: confirmed watchdog process sets no `rls.role`, validated SECDEF deferral path.

### Pattern recognition

This is the third audit confirming **doc/DB drift is recurring**. Always query
live `pg_policies` before locking deploy plans. Live DB > handoff text.
