# Stage 5d Design — Writer Role Cutover (Narrowed Scope)

**Date:** 2026-04-10
**Author:** Ken + Air Claude (review), Sandbox Claude (discovery)
**Discovery doc:** STAGE5D_DISCOVERY.md
**Status:** Phase 2 design — ready for execution

---

## Scope Decision

This design **narrows Stage 5d** from the original brief because:

1. R2 (TaskGraphExecutor invalid status values) is **dormant** — task tables are empty, no production traffic exercises the broken paths
2. **TaskGraphExecutor is likely to be replaced by Temporal in Alpha-2** — fixing R2 would be wasted work
3. R1 (GUC mismatch) is the only **must-fix** for the cutover to succeed

**In scope:**
- 5d.1: watchdog_agent cutover to writer role
- 5d.2: executor cutover to writer role + R1 GUC fix + delete dead code

**Out of scope (deferred):**
- R2 status value fixes → TD-53, fix only if Temporal POC fails
- FORCE RLS on task tables → Stage 5e
- New SECDEF wrappers → not needed under narrowed scope

---

## Stage 5d.1 — watchdog_agent Cutover

### Goal
Flip `watchdog_agent.py` from `jarvisbrain` (BYPASSRLS) to `jarvis_alpha_writer` with no behavior change.

### Changes

**1. New env var in `~/jarvis/.secrets` on Brain:**
ALPHA_DB_DSN_WATCHDOG_AGENT=postgresql://jarvis_alpha_writer:<password>@localhost/jarvis_alpha

Backup `~/jarvis/.secrets.bak_pre_5d1` before edit.

**2. Code change in `brain/agents/watchdog_agent.py:358`:**

From:
```python
os.environ["ALPHA_DB_DSN"]
```

To:
```python
get_secret("ALPHA_DB_DSN_WATCHDOG_AGENT")
```

(Removes direct `os.environ` anti-pattern AND uses new var.)

**3. No SECDEF wrappers needed.** Both tables touched are already safe under writer:
- `alpha_node_registry` — no RLS, has SELECT/INSERT/UPDATE/DELETE grants for `jarvis_alpha_app`
- `alpha_watchdog_events` — RLS uses `rls.user_id='system'`, watchdog_agent already sets it correctly at line 122

**4. No GUC changes.** `rls.user_id='system'` is correct.

### Smoke Test (`scripts/smoke_5d1_watchdog_agent.sh`)

Must verify under `jarvis_alpha_writer`:
1. Connect to DB with new DSN — succeeds
2. SELECT from `alpha_node_registry` — returns >0 rows
3. INSERT test row into `alpha_watchdog_events` with `rls.user_id='system'` set — succeeds
4. DELETE that test row — succeeds
5. Negative test: connect WITHOUT setting `rls.user_id`, attempt INSERT — must FAIL (proves RLS is enforced)

Exit 0 on full pass.

### Rollback
- Revert single line in watchdog_agent.py
- Restore `~/jarvis/.secrets.bak_pre_5d1`
- `launchctl kickstart -k gui/$(id -u)/com.jarvis.alpha.watchdog`

### Soak
- 24h minimum
- Pass criteria: zero ERROR entries in `alpha_watchdog.log`, watchdog cycles continue every 60s, `up=N down=0` consistent

---

## Stage 5d.2 — Executor Cutover + R1 GUC Fix + Cleanup

### Goal
Flip executor.py to writer role, fix the GUC value bug, delete dead code.

### Changes

**1. New env var in `~/jarvis/.secrets`:**
ALPHA_DB_DSN_EXECUTOR=postgresql://jarvis_alpha_writer:<password>@localhost/jarvis_alpha

**2. Code changes in `brain/tasks/executor.py`:**

R1 fix (4 lines across 2 functions):
- Line 46: `set_config('jarvis.current_user', 'admin', true)` → `set_config('jarvis.current_user', 'platform_admin', true)`
- Line 47: `set_config('jarvis.role', 'admin', true)` → `set_config('jarvis.role', 'platform_admin', true)`
- Line 480: same change
- Line 481: same change

DSN change at line 42:
- `get_secret("JARVIS_ALPHA_DB_DSN")` → `get_secret("ALPHA_DB_DSN_EXECUTOR")`

**3. Delete dead code:**
- `rm brain/tasks/watchdog.py`
- Verify no imports: `grep -rn "from brain.tasks.watchdog" ~/jarvis-alpha/brain/` must return 0 lines
- Verify no plist references in `~/jarvis-alpha/launchagents/`

**4. R2 status fix — DEFERRED.** TD-53 stays open. If Temporal POC succeeds, executor.py gets deleted entirely. If Temporal POC fails or is deferred, R2 fix happens in a follow-up session.

### Smoke Test (`scripts/smoke_5d2_executor.sh`)

Must verify under `jarvis_alpha_writer` with `jarvis.role='platform_admin'`:
1. Connect with new DSN — succeeds
2. INSERT test row into `alpha_task_graphs` (status='pending', graph_type='maintenance') — succeeds
3. SELECT the row back — returns 1 row (proves RLS allows the read under correct GUC)
4. UPDATE the row to status='running' — succeeds
5. INSERT test step into `alpha_task_steps` — succeeds
6. UPDATE step to status='completed' — succeeds
7. UPDATE graph to status='completed' — succeeds
8. DELETE step + graph — succeeds (cleanup)
9. Negative test: same connection with `jarvis.role='wrong_value'` — SELECT must return 0 rows (proves RLS filters)

Exit 0 on full pass. **The negative test is critical** — it proves the GUC fix actually works and we're not just bypassing RLS by accident.

### Rollback
- `git revert HEAD`
- Restore `~/jarvis/.secrets.bak_pre_5d2`
- `launchctl kickstart -k gui/$(id -u)/com.jarvis.alpha.executor`
- If watchdog.py delete causes issues: file is in git history, `git checkout HEAD~1 -- brain/tasks/watchdog.py`

### Soak
- 24h minimum
- Pass criteria: executor stays alive, no ERROR entries in `alpha_executor.log`, manual smoke re-run after 24h still green

---

## Migration List
**Zero migrations.** All changes are code + env vars + dead-code deletion. No schema changes, no GRANT changes, no policy changes.

---

## Risk Table

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | GUC value `'admin'` vs policy expects `'platform_admin'` | BLOCKER → FIXED in 5d.2 | 4-line code change + smoke test negative case |
| R2 | TaskGraphExecutor invalid status values | DORMANT → TD-53 deferred | Will be deleted entirely if Temporal POC succeeds |
| R3 | Silent-failure monitoring gap | LOW (empty tables) | TD-56 logged for after Temporal decision |
| R4 | tasks/watchdog.py dead code | RESOLVED in 5d.2 | Delete |
| R5 | Env var inconsistency across services | RESOLVED | Standardized to `ALPHA_DB_DSN_<SERVICE>` per Stage 5c pattern |
| R6 | `app.profile_role` GUC unsatisfied | LOW | Defer to Stage 5e (FORCE RLS prep) |
| R7 | alpha_task_events forward migration undocumented | LOW | TD-50 logged |

---

## Sequencing
- **Day 1:** Ship 5d.1
- **Day 2:** Soak 5d.1 + Temporal POC evening
- **Day 3:** Ship 5d.2 (assuming 5d.1 soak green)
- **Day 4:** Soak 5d.2
- **Day 5:** Decision point — Temporal go/no-go for Alpha-2

**Stages 5d.1 and 5d.2 must NOT ship in the same session.** 24h soak between is mandatory per Stage 5c lesson.

---

## TD Updates From This Design
- **TD-53** (NEW, P0-when-decided): TaskGraphExecutor invalid status values — fix in follow-up OR delete entire file if Temporal adopted
- **TD-54** (NEW, RESOLVED in 5d.2): Delete tasks/watchdog.py
- **TD-55** (NEW, INFO): Task tables empty — TaskGraph build-out unstarted
- **TD-56** (NEW, P2): Silent-failure monitoring for executor — implement after Temporal decision
