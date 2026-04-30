# Slab 2 — GUC Namespace Migration Deploy Plan

**Status:** LOCKED — ready for Cursor execution
**Locked:** 2026-04-30
**Builds on:** Slab 1 (pgAudit shipped Apr 29) — service-quiesce pattern reused
**Locks Q1=B / Q2=B / Q3=A** from Apr 30 architecture review

---

## Purpose

Migrate every `jarvis.*` and `app.*` GUC reference in jarvis-alpha to a single canonical `rls.*` namespace, atomically across DB policies and 9 Python files. Eliminates dual-namespace tech debt that has accumulated since Step 7 architecture work began.

---

## What changes

### GUC namespace flip

| Old GUC | New GUC | Notes |
|---|---|---|
| `jarvis.current_user` | `rls.user_id` | Primary identity GUC |
| `jarvis.role` | `rls.role` | Role check ('user', 'platform_admin', etc.) |
| `app.user_id` | DROP | Duplicate of `rls.user_id`, never read in policies |
| `app.max_rating` | `rls.max_rating` | Child profile content rating ceiling |
| `app.workspace_id` | `rls.workspace_id` | Workspace scope |
| `jarvis.is_admin` | DROP | 3 reads, 0 writes — inoperative escape hatch (Task C finding) |

Final namespace: **5 GUCs, single `rls.*` prefix.**

### NOT in this slab

- `rls.calling_agent` tripwire — deferred to Slab 4 per Q2=B (no-op until SECDEF fleet expands)
- SECDEF function expansion — Slab 4
- Policy template canonicalization (Shape A/B) — Slab 3
- FORCE RLS atomic flip — Slab 6

---

## Files affected

### Python (9 files setting GUCs + N reading)

**Group 1 — Central helper (1 file):**
- `brain/db/rls.py` — `set_request_guc()` middleware helper. **Highest blast radius.**

**Group 2 — Call sites (7 files):**
- `brain/dream/_db.py`
- `brain/tasks/executor.py`
- `brain/routes/dream_planning.py`
- `brain/routes/internal_cost.py`
- `brain/routes/dev.py`
- `brain/services/dream_cost_cap_service.py`
- `brain/services/dream_invariant_checker.py`

**Group 3 — Gateway (1 file):**
- `gateway/dream/kill_switch.py`

### SQL — Policy rewrite migration

One migration file to write, executed as a single transaction:
- `brain/db/migrations/YYYYMMDD_HHMMSS_guc_namespace_migration.sql`

Contains:
1. `DROP POLICY` for every policy referencing `jarvis.*` or `app.*`
2. `CREATE POLICY` with same logic but `rls.*` references
3. Drop `app.*` and `jarvis.is_admin` references
4. Verification block — count policies, error if any `jarvis.*` or `app.*` remains

---

## Deploy sequence (Q3=A — service quiesce, mirrors Slab 1)

### Phase 0 — Pre-flight (5 min)

▶ BRAIN —
```
echo "=== Postgres still 16.13 with pgAudit? ===" && \
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -d jarvis_alpha -U jarvisbrain -c "SHOW shared_preload_libraries;" && \
echo "=== Capture pre-deploy policy state ===" && \
mkdir -p ~/jarvis-alpha/logs/slab2_deploy_$(date +%Y%m%d) && \
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -d jarvis_alpha -U jarvisbrain -c "\copy (SELECT * FROM pg_policies ORDER BY tablename, policyname) TO '~/jarvis-alpha/logs/slab2_deploy_$(date +%Y%m%d)/before_pg_policies.tsv'" && \
echo "=== Service health baseline ===" && \
launchctl list | grep -iE "jarvis|temporal" | sort > ~/jarvis-alpha/logs/slab2_deploy_$(date +%Y%m%d)/before_services.txt && \
cat ~/jarvis-alpha/logs/slab2_deploy_$(date +%Y%m%d)/before_services.txt && \
echo "=== Audit count baseline ===" && \
grep -c "AUDIT:" /opt/homebrew/var/log/postgresql@16.log
```

**Pass criteria:** pgAudit loaded, all 7 services exit 0, baseline files written.

### Phase 1 — Deploy code (Cursor work, ~30 min)

Three Cursor prompts in order:
1. **Group 1** — `brain/db/rls.py` central helper
2. **Group 2** — 7 call site files (single prompt)
3. **Group 3** — `gateway/dream/kill_switch.py` (Gateway-side)

After each prompt: verify file diffs, syntax check, no commit yet.

### Phase 2 — Write SQL migration (Cursor prompt #4)

Single migration file with:
- DROP POLICY for every old-namespace policy
- CREATE POLICY with new namespace
- Verification SELECT at end (should return 0 rows of `jarvis.*` or `app.*` references)

### Phase 3 — Commit all 4 changes (single commit)

▶ AIR —
```
cd ~/jarvis-alpha && bash scripts/jarvisalpha_commit.sh "feat(rls-step7): Slab 2 — GUC namespace migration jarvis.*/app.* → rls.*"
```

Migration runner on Brain pull will FAIL (services still running with old GUC names → policies don't match → DB writes start failing). **This is expected.** Pull halts, services keep running with old code on old policies. We then quiesce + apply.

### Phase 4 — Service quiesce + apply (mirrors Slab 1)

Same 7-service stop/start pattern as Slab 1:

▶ BRAIN — stop sequence
```
UID_BRAIN=$(id -u) && \
for svc in com.jarvis.alpha.buddy com.jarvis.alpha.watchdog com.jarvis.alpha.executor com.jarvis.family.api com.jarvis.alpha.brain com.jarvis.alpha.temporal.ui com.jarvis.alpha.temporal.server; do
  echo "=== stopping $svc ==="
  launchctl bootout gui/$UID_BRAIN/$svc 2>&1 | head -3 || true
  sleep 2
done && \
launchctl list | grep -iE "jarvis|temporal" | sort
```

▶ BRAIN — verify drain
```
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -d jarvis_alpha -U jarvisbrain -c "SELECT datname, count(*) FROM pg_stat_activity WHERE datname IN ('jarvis_alpha','temporal','temporal_visibility') GROUP BY datname;"
```

Expected: 1 connection on jarvis_alpha (psql itself), 0 on temporal DBs.

▶ BRAIN — run migration
```
cd ~/jarvis-alpha && bash scripts/apply_migrations.sh 2>&1 | tail -30
```

▶ BRAIN — verify zero old-namespace references remain
```
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -d jarvis_alpha -U jarvisbrain -c "SELECT count(*) FROM pg_policies WHERE qual LIKE '%jarvis.%' OR qual LIKE '%app.%' OR with_check LIKE '%jarvis.%' OR with_check LIKE '%app.%';"
```

Expected: `0`.

▶ BRAIN — start sequence (reverse dep order)
```
UID_BRAIN=$(id -u) && \
for svc in com.jarvis.alpha.temporal.server com.jarvis.alpha.temporal.ui com.jarvis.alpha.brain com.jarvis.family.api com.jarvis.alpha.executor com.jarvis.alpha.watchdog com.jarvis.alpha.buddy; do
  PLIST=~/Library/LaunchAgents/$svc.plist
  echo "=== starting $svc ==="
  if [ -f "$PLIST" ]; then
    launchctl bootstrap gui/$UID_BRAIN "$PLIST" 2>&1 | head -3 || true
  fi
  sleep 3
done && \
launchctl list | grep -iE "jarvis|temporal" | sort
```

### Phase 5 — Smoke test (5 min)

▶ BRAIN —
```
echo "=== Brain health ===" && \
curl -ks https://jarvis-brain.tail40ed36.ts.net:8186/health && \
echo "" && \
echo "=== Connection counts ===" && \
/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -d jarvis_alpha -U jarvisbrain -c "SELECT datname, count(*) FROM pg_stat_activity WHERE datname IN ('jarvis_alpha','temporal','temporal_visibility') GROUP BY datname;" && \
echo "=== RLS smoke — create + read message in own thread ===" && \
echo "(runtime-specific test; manual psql session with rls.user_id set, attempt SELECT on chat_messages)" && \
echo "=== Brain error log last 2 min ===" && \
find ~/jarvis-alpha/logs -name "alpha_brain*error*.log" -mmin -2 -exec tail -5 {} \; && \
echo "=== Audit count growth ===" && \
grep -c "AUDIT:" /opt/homebrew/var/log/postgresql@16.log
```

**Pass criteria:**
- `/health` ok
- Connection counts return to normal (jarvis_alpha 5-15, temporal 25-35)
- No new errors in alpha_brain*error.log
- Audit count growing
- RLS smoke: queries with `rls.user_id` set return rows, queries without it return empty

---

## Rollback path

### Pre-commit rollback (during Phase 1-2)
- Cursor changes uncommitted → discard with `git checkout -- <files>`

### Post-commit, pre-migration rollback (during Phase 3)
- Migration runner halted → `git revert HEAD && bash scripts/jarvisalpha_commit.sh "revert: <sha>"`
- Services keep running with old GUCs on old policies (no state change in DB)

### Post-migration rollback (during Phase 4)
- Migration applied, services already stopped
- Rollback migration prebuilt (DROP new policies, recreate old policies, restore old code via revert)
- Run rollback migration → restart services with old code
- Maximum 5 min downtime

### Rollback migration (also written by Cursor, kept ready)
- Filename: `brain/db/migrations/YYYYMMDD_HHMMSS_revert_guc_namespace.sql`
- Mirror image of forward migration
- NOT applied unless rollback needed

---

## Risk register

| Risk | Mitigation |
|---|---|
| Forgot a Python file | Group 2 prompt has Cursor grep for `jarvis\.\(current_user\|role\)` and `app\.` after edit; any remaining match fails verification |
| Policy SQL syntax error | Migration runs in transaction — failure rolls back automatically |
| RLS smoke test reveals policies fail-closed (no rows returned) | Likely a `rls.user_id` not set in `rls_connection()`; rollback, fix middleware, re-deploy |
| Watchdog SIGTERM returns post-restart | TD-94 returning is independent of Slab 2; capture and continue |
| Temporal worker connection storm | Sleeps in start sequence prevent thundering herd |

---

## Acceptance criteria

| Check | Pass signal |
|---|---|
| `pg_policies` query for `jarvis.%` or `app.%` references | `count = 0` |
| All 7 services restart with PID + exit 0 | ✅ |
| Brain `/health` | `{"status":"ok"}` |
| pgAudit lines growing | yes |
| RLS smoke (set `rls.user_id`, SELECT chat_messages) | returns rows |
| RLS smoke (no GUC set, SELECT chat_messages) | returns 0 rows (fail-closed) |
| 30-min soak | no new ERROR/FATAL in postgres log |

---

## Tech debt captured

This slab closes:
- TD-162 (was the original GUC consolidation; superseded by Slab 2)
- The "9 Python files" tech debt from Apr 27 GUC code surface inventory

This slab does NOT close (deferred to later slabs):
- TD-156 cost_emitter circuit breaker
- TD-94 watchdog SIGTERM (Slab 4 LISTEN/NOTIFY rebuild)
- TD-161 no-RLS-table audit (Slab 6)
- The 5 surprises from Task B (Slab 6 re-cut)

---

*Slab 2 deploy plan — locked 2026-04-30. Reuses Slab 1 service-quiesce pattern. Mirrors Slab 1 deploy cadence.*
