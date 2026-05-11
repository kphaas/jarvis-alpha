# DISCOVERY — Slab 4 Phase 1b: Caller-side audit (Class B pattern holes)

- **Date:** 2026-05-11
- **Scope:** Read-only audit of every raw `pool.acquire()` callsite in `brain/` against the FORCE-RLS table set, looking for the Class B pattern hole: callsite queries a FORCE-RLS table on a raw pool connection without setting `rls.role` first. Companion to Phase 1a (SECDEF function audit).
- **Author:** Claude Code (read-only)
- **Local repo HEAD:** `b97e425` 2026-05-11 `fix(approvals): TD-211 elevate approval queue read to platform_admin (#87)`

## 1. Spec invariants honoured

- Read-only: no code edits, no DB writes.
- One diagnostic SELECT executed against Brain to empirically verify the failure mode (§4); this issued `SET ROLE jarvis_alpha_writer; SELECT count(*); RESET ROLE` only — no INSERT/UPDATE/DELETE.
- FORCE-RLS set is the 21-table inventory from Phase 1a §2.

## 2. Scoping decision (logged before classification)

Initial `grep -rn '\.acquire()'` in `brain/` returned **70 callsites across 27 files**. This exceeds the marathon §B.4 stop threshold of 50. Per Ken's direction: apply a **programmatic FORCE-RLS-name prefilter** to each file. Files whose contents grep to zero FORCE-RLS table names get a one-line clear ("no FORCE-RLS table references — out of scope"); files with hits get deep classification per callsite.

**Prefilter result:** 13 files in deep-audit scope (≈32 callsites), 14 files grep-cleared (≈38 callsites).

## 3. Classification table

### 3a — Deep-audited callsites

| File:line | Function | Tables queried | rls.role set before query? | Class | Severity | Evidence |
|---|---|---|---|---|---|---|
| brain/middleware/approval.py:151 | `_get_approved_queue_id` (TD-211 fix) | alpha_approval_queue (read) | YES — inline `set_config('rls.role','platform_admin',true)` line 154 | OK | — | TD-211 hotfix landed in PR #87 |
| brain/middleware/approval.py:177 | `_consume_approved_queue` | (via SECDEF `consume_approved_queue_item`) | n/a (SECDEF call) | OK (calls SECDEF wrapper) | — | line 178-181 |
| brain/middleware/approval.py:198 | `_queue_for_approval` error fallback | First call OK via SECDEF; **then raw SELECT alpha_approval_queue at line 216-224 in UniqueViolationError handler — same `acquire()` block, no extra set_config** | NO for fallback read | **Pattern hole** | HIGH (read in error path) | UniqueViolationError handler does raw SELECT; today returns 0 rows under the writer-role connection → falls through to `return None` → duplicate approval requests would not be deduplicated |
| brain/routes/dream.py:65 | `create_session` POST | INSERT alpha_dream_sessions | NO | **Pattern hole** | **CRITICAL (write)** | §4 empirical check confirms writer sees 0 rows; INSERT must raise RLS WITH CHECK violation or silently fail |
| brain/routes/dream.py:132 | `start_session` POST | UPDATE alpha_dream_sessions status='running' | NO | **Pattern hole** | **CRITICAL (write)** | same as above |
| brain/routes/dream.py:160 | `kill_session` POST | UPDATE alpha_dream_sessions status='killed' | NO | **Pattern hole** | **CRITICAL (write)** | same |
| brain/routes/dream.py:201 | `get_next_step` GET | SELECT alpha_dream_sessions + alpha_dream_steps | NO | **Pattern hole** | HIGH (read) | reads return 0 rows under writer-role |
| brain/routes/dream.py:261 | `update_step` PATCH | UPDATE alpha_dream_steps | NO | **Pattern hole** | **CRITICAL (write)** | |
| brain/routes/dream.py:356 | `complete_session` POST | UPDATE alpha_dream_sessions, SELECT alpha_dream_steps | NO | **Pattern hole** | **CRITICAL (write)** | |
| brain/routes/chat.py:377 | `_store_memory_bg` | MemoryService.store → SECDEF `store_conversation_memory` (verified at brain/memory/memory.py:252) | n/a (SECDEF call) | OK | — | calls SECDEF |
| brain/routes/approvals.py:43 | `unlock_approvals` POST | SELECT alpha_profiles | n/a — `alpha_profiles` is NOT in the FORCE-RLS set | OK-not-applicable | — | grep cleared for alpha_profiles |
| brain/routes/dream_planning.py:73 | (route handler) | reads dream tables | YES — inline `set_config('rls.role','platform_admin',true)` line 75 | OK | — | |
| brain/routes/dev.py:209 | (dev route 1) | dev/diagnostic | YES — lines 55, 59 (file-level helper sets rls.role + rls.user_id) | OK | — | |
| brain/routes/dev.py:269 | (dev route 2) | dev/diagnostic | YES — lines 274, 278 | OK | — | |
| brain/routes/watchdog.py:127 | `list_events` GET | SELECT alpha_watchdog_events (read + COUNT) | NO | **Pattern hole** | HIGH (read) | empirical: writer sees 0 rows; the endpoint silently returns empty list under non-superuser pool |
| brain/routes/watchdog.py:169 | `get_status` GET | SELECT DISTINCT ON alpha_watchdog_events | NO | **Pattern hole** | HIGH (read) | endpoint takes no `request` param — also a convention break (admin route with no auth surface) |
| brain/routes/watchdog.py:220 | `ingest_event` POST | SECDEF `record_watchdog_event` | n/a (SECDEF call) | OK | — | |
| brain/tasks/executor.py:189 | `run_graph` | UPDATE alpha_task_graphs status='running', SELECT alpha_task_graphs | YES — `_bind_executor_rls(conn)` at line 190 sets `rls.role='platform_admin'` (definition at line 44) | OK | — | _bind_executor_rls is the executor's canonical helper |
| brain/tasks/executor.py:452 | executor main loop | SELECT alpha_task_graphs WHERE status IN(...) + JOIN alpha_task_steps | YES — `_bind_executor_rls(conn)` line 453 | OK | — | |
| brain/tasks/executor.py:510 | `recover_stuck_graphs` | UPDATE alpha_task_graphs status='pending' | YES — `_bind_executor_rls(conn)` line 511 | OK | — | |
| brain/services/dream_invariant_checker.py:142 | (checker method 1) | dream invariants | YES — inline `set_config('rls.role','platform_admin',true)` line 145 | OK | — | |
| brain/services/dream_invariant_checker.py:303 | (checker method 2) | dream invariants | YES — line 306 | OK | — | |
| brain/services/dream_cost_cap_service.py:43 | (cost cap method 1) | dream cost cap reads/writes | YES — inline `set_config('rls.role','platform_admin',true)` line 46 | OK | — | |
| brain/services/dream_cost_cap_service.py:125 | (cost cap method 2) | dream cost cap | YES — line 128 | OK | — | |
| brain/agents/buddy_agent.py:63 | `_write_event` | SECDEF `record_buddy_event` | n/a (SECDEF call) | OK | — | |
| brain/agents/buddy_agent.py:80 | `_expire_pending_approvals` | SECDEF `expire_pending_approvals` | n/a (SECDEF call) | OK | — | comment at line 76-77 is stale — SECDEF wrapper already exists |
| brain/agents/buddy_agent.py:92 | `_run_cycle` user list | SECDEF `list_active_memory_users` | n/a (SECDEF call) | OK | — | |
| brain/agents/buddy_agent.py:101 | maintenance per-user | SECDEF `run_buddy_memory_maintenance` | n/a (SECDEF call) | OK | — | |
| brain/agents/buddy_agent.py:117 | promotion candidates | SECDEF `get_buddy_promotion_candidates` | n/a (SECDEF call) | OK | — | |
| brain/agents/watchdog_agent.py:121 | `_persist_event` | SECDEF `record_watchdog_event` | n/a (SECDEF call) | OK | — | |
| brain/agents/watchdog_agent.py:197 | `_load_services` | SELECT alpha_node_registry | n/a — `alpha_node_registry` is NOT in the FORCE-RLS set | OK-not-applicable | — | grep cleared for alpha_node_registry |
| brain/db/rls.py:78 | `rls_connection` helper itself | n/a (this is the canonical wrapper) | YES — sets rls.role + rls.user_id + rls.max_rating + rls.workspace_id (lines 82-93) | OK (canonical) | — | this IS the helper everyone else should be using |

### 3b — Grep-cleared modules (out-of-scope for Class B)

Each was confirmed via `grep -E "$FORCE_RLS_PATTERN" <file>` returning zero matches against the 21-name pattern. One line of evidence per file:

| File | .acquire() count | Grep result against FORCE-RLS set |
|---|---|---|
| brain/services/approval_notifier.py | 1 | 0 hits — no FORCE-RLS table reference |
| brain/routes/security.py | 1 | 0 hits |
| brain/routes/rotation.py | 1 | 0 hits |
| brain/routes/prompts.py | 3 | 0 hits |
| brain/routes/pin_auth.py | 5 | 0 hits |
| brain/routes/mesh.py | 1 | 0 hits |
| brain/routes/internal_cost.py | 1 | 0 hits (and additionally sets rls.role at line 96 — pre-emptively safe) |
| brain/routes/honeypot.py | 2 | 0 hits |
| brain/routes/costs.py | 14 | 0 hits (touches `alpha_cloud_costs` — RLS-enabled but NOT FORCE-RLS, so writer-role's policy access suffices) |
| brain/routes/briefings.py | 4 | 0 hits |
| brain/middleware/log_middleware.py | 1 | 0 hits |
| brain/dream/_db.py | 1 | 0 hits (and additionally sets rls.role at lines 34-36 — pre-emptively safe) |
| brain/core/db.py | 1 | 0 hits |
| brain/audit/secret_audit.py | 2 | 0 hits |

Verification trail: per-file FORCE-RLS-pattern grep was run via the 21-name alternation pattern; results captured at audit time.

## 4. Empirical failure-mode confirmation

The dream.py pattern hole is not theoretical. Live SQL on Brain confirms the failure mode:

```sql
SET ROLE jarvis_alpha_writer;
SELECT count(*) FROM alpha_dream_sessions;   -- returns 0
SELECT set_config('rls.role','platform_admin',false);
SELECT count(*) FROM alpha_dream_sessions;   -- returns 5
RESET ROLE;
```

`jarvis_alpha_writer` (pool's connection role — confirmed via `brain/app.py:49` `init_pool(ALPHA_DB_DSN_WRITER)`) has `rolbypassrls=f, rolsuper=f`. The only PERMISSIVE policy on `alpha_dream_sessions` is `dream_sessions_platform_admin` keyed on `current_setting('rls.role')='platform_admin'`. Without setting that GUC, the writer connection cannot read or write the table.

This means the 5 critical write callsites in `brain/routes/dream.py` are **broken in production today, not just at Slab 7c**. Either:

- (a) The endpoints have been failing in production with RLS WITH-CHECK errors on INSERT/UPDATE and nobody has noticed because dream is exercised through a different path (CLI? executor?).
- (b) The 5 actual rows in `alpha_dream_sessions` were created by a path other than these routes (e.g. directly via psql or via a fixture; or via the executor which has its own RLS binding).
- (c) The endpoints succeed because some upstream middleware sets `rls.role` we haven't seen in this scope. **No such middleware exists** — the only places that set `rls.role` are listed in §3a, and `brain/routes/dream.py` is not among them.

Phase 2 fleet write should treat these as live bugs, not Slab 7c-deferred risk.

## 5. Ranked findings

### CRITICAL (write to FORCE-RLS table, broken today, silent or hard fail):
1. `brain/routes/dream.py:65` — INSERT alpha_dream_sessions (create_session)
2. `brain/routes/dream.py:132` — UPDATE alpha_dream_sessions (start_session)
3. `brain/routes/dream.py:160` — UPDATE alpha_dream_sessions (kill_session)
4. `brain/routes/dream.py:261` — UPDATE alpha_dream_steps (update_step)
5. `brain/routes/dream.py:356` — UPDATE alpha_dream_sessions (complete_session)

### HIGH (read FORCE-RLS table, silently 0 rows under writer-role):
6. `brain/routes/dream.py:201` — SELECT alpha_dream_sessions/steps (get_next_step)
7. `brain/routes/watchdog.py:127` — SELECT alpha_watchdog_events list (GET /v1/watchdog/events)
8. `brain/routes/watchdog.py:169` — SELECT alpha_watchdog_events DISTINCT ON (GET /v1/watchdog/status)
9. `brain/middleware/approval.py:198` — raw SELECT alpha_approval_queue in UniqueViolationError handler within `_queue_for_approval`

### OK count
21 callsites in deep-audit scope are OK (set rls.role themselves OR call a SECDEF wrapper OR query a non-FORCE table). 38 callsites in grep-cleared scope are OK-by-table.

### Ambiguous: 0

## 6. Recommended Phase 2 fleet fix order

Fixes can group by file because each pattern-hole route in dream.py and watchdog.py is in the same file:

1. **PR #1 — brain/routes/dream.py** (6 callsites). All 6 routes have `request: Request` already. The canonical fix is **swap raw `pool.acquire()` for `rls_connection(request)`** — the routes are HTTP-bound and `rls_connection` derives rls.role from JWT (admin/user/child) automatically. This is the most idiomatic fix and matches the helper's documented purpose (brain/db/rls.py:4-7). Open question: dream sessions are inherently platform-level operations. Routes might need a small `request.state.role` elevation pattern, or a forced platform_admin override for dream routes specifically. Recommend Ken decide between (i) `rls_connection` + JWT-role-based, or (ii) inline `set_config('rls.role','platform_admin',true)` matching the dream_planning.py pattern.
2. **PR #2 — brain/routes/watchdog.py** (2 callsites: lines 127, 169). The watchdog read routes (`list_events`, `get_status`) have NO `request: Request` parameter today — secondary convention violation. Fix is twofold: (a) add `request: Request` to the signature, (b) use `rls_connection(request)`. If routes need to remain auth-free for ops visibility, the inline `set_config` route is the alternative.
3. **PR #3 — brain/middleware/approval.py** (1 callsite: line 198 error fallback). Tightest scope — just add a `set_config('rls.role','platform_admin',true)` call inside the `acquire` block BEFORE the SECDEF call AND keep it in scope for the UniqueViolationError raw SELECT. One-line fix.

## 7. Quantification

- Deep-audited callsites: 32 across 13 files.
- Grep-cleared callsites: 38 across 14 files.
- Total .acquire() callsites in brain/: 70.
- Pattern-hole count: 9 (5 critical writes + 4 high reads).
- Files needing changes: 3 (dream.py, watchdog.py, approval.py).
- Estimated total work: ≤30 lines of code change across the 3 PRs.

## 8. Open questions for Ken

1. **Empirical contradiction in §4.** alpha_dream_sessions has 5 actual rows. Where did they come from if `brain/routes/dream.py` cannot insert? Possibilities: psql/test fixture, executor.py's `_bind_executor_rls`-bound path, an older codepath since removed. This matters for PR #1's regression risk — if dream.py's `POST /sessions` has been hard-failing in production, fixing it changes user-visible behavior and may unblock a previously-broken feature.
2. **PR #1 design choice: rls_connection (JWT-role-based) vs inline set_config('platform_admin').** Dream sessions are not per-user-scoped (no `owner_profile` filter on alpha_dream_sessions). They're platform-level objects. `rls_connection` would derive `rls.role` from JWT (admin/user/child), and only admins could create sessions. Inline `platform_admin` would let any authenticated route caller create sessions. Which is the desired auth model?
3. **PR #2 design choice for watchdog routes.** `list_events` and `get_status` have no `request` param today — observed convention is that these are unauthenticated diagnostic endpoints. If we add auth, behaviour changes; if we don't, we need inline `set_config`. Which?
4. **Convention codification.** The audit shows TWO patterns in production for "background-but-needs-RLS": `_bind_executor_rls` (executor.py) and inline `set_config('rls.role','platform_admin',true)` (services, middleware). Should one become THE canonical pattern? Suggest factoring both into a `brain/db/rls.py` helper named `platform_admin_connection()` analogous to `rls_connection()` — could land alongside PR #1-#3.
5. **Stale comment cleanup.** `brain/agents/buddy_agent.py:76-77` carries a TD comment incorrectly claiming approval-table writes need SECDEF wrapping; the SECDEF wrapper (`expire_pending_approvals`) already exists. Fold a one-line comment fix into PR #3, or open a separate trivial PR?

## 9. Artifacts

- Callsite inventory: `/tmp/acquire_strict.txt` on Sandbox (transient).
- File-scope filter: `/tmp/acquire_files.txt`.
- Companion: `DISCOVERY_2026-05-11_slab4_phase1a_secdef_audit.md`.
