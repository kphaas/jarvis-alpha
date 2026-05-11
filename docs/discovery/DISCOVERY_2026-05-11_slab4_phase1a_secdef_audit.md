# DISCOVERY — Slab 4 Phase 1a: SECDEF function audit (Class A pattern holes)

- **Date:** 2026-05-11
- **Scope:** Read-only audit of every SECURITY DEFINER function in the JARVIS schema (`public`) for the Class A pattern hole: function operates on a FORCE-RLS table without internally setting `rls.role='platform_admin'`. Companion doc to Phase 1b (caller-side audit).
- **Author:** Claude Code (read-only)
- **Local repo HEAD:** `b97e425` 2026-05-11 `fix(approvals): TD-211 elevate approval queue read to platform_admin (#87)`
- **Brain DB query timestamp:** 2026-05-11 (live)

## 1. Spec invariants honoured

- All psql via SSH to Brain (`/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql`, user `jarvisbrain`, DB `jarvis_alpha`).
- FORCE-RLS detection via `pg_class.relforcerowsecurity` (NOT `pg_tables.forcerowsecurity` — that column does not exist).
- No DB writes. No code changes. Read-only DDL introspection only.
- All `alpha_*` table names confirmed via `\d` before any cross-reference query.

## 2. FORCE-RLS table inventory

Query: `SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c JOIN pg_namespace n ON c.relnamespace=n.oid WHERE c.relkind='r' AND c.relrowsecurity=true ORDER BY c.relforcerowsecurity DESC, c.relname;`

**21 tables in the FORCE-RLS set** (all `relforcerowsecurity = true`):

| # | Table | Notes |
|---|---|---|
| 1 | `alpha_approval_audit` | append-only audit; pattern-hole-touched by 3 SECDEF fns |
| 2 | `alpha_approval_queue` | TD-211 surface |
| 3 | `alpha_buddy_events` | events table for buddy agent |
| 4 | `alpha_conversation_memory` | large hot path (8 SECDEF fns touch it) |
| 5 | `alpha_dream_blocked_writes` | dream invariant violations |
| 6 | `alpha_dream_cost_caps` | dream cost cap config |
| 7 | `alpha_dream_cost_counters` | dream per-session cost tally |
| 8 | `alpha_dream_model_policy` | dream model allowlist |
| 9 | `alpha_dream_sessions` | dream control table |
| 10 | `alpha_dream_steps` | dream step table |
| 11 | `alpha_semantic_memory` | semantic memory writes |
| 12 | `alpha_system_flags` | system-wide flags |
| 13 | `alpha_task_events` | task graph events |
| 14 | `alpha_task_graphs` | task graph control |
| 15 | `alpha_task_steps` | task graph steps |
| 16 | `alpha_watchdog_events` | observability table |
| 17 | `chat_messages` | per-thread messages |
| 18 | `chat_threads` | thread metadata |
| 19 | `vault_access_log` | vault access audit |
| 20 | `vault_documents` | vault content (RLS-protected) |
| 21 | `vault_pipeline` | vault ingest pipeline |

One additional RLS-but-not-FORCED table (out of scope for this audit): `alpha_cloud_costs`.

## 3. SECDEF function inventory (`public` schema, JARVIS-owned)

Query: `SELECT proname, proowner::regrole::text, COALESCE(array_to_string(proconfig,';'),'') FROM pg_proc WHERE prosecdef=true AND pronamespace='public'::regnamespace ORDER BY proname;`

**19 JARVIS-owned SECDEF functions** (2 pgaudit internals skipped: `pgaudit_ddl_command_end`, `pgaudit_sql_drop`). All owned by `jarvisbrain` (superuser, `rolsuper=t`, `rolbypassrls=t`). NONE have `rls.role=platform_admin` in `proconfig`.

## 4. Per-function classification

| Function | Owner | `proconfig` rls.role? | Inline `set_config('rls.role',...)` in body? | FORCE-RLS tables touched | Class | Severity |
|---|---|---|---|---|---|---|
| `bump_memory_access` | jarvisbrain | — | NONE | alpha_conversation_memory | Pattern hole | HIGH |
| `cap_episodic_memory` | jarvisbrain | — | NONE | alpha_conversation_memory | Pattern hole | HIGH |
| `cap_semantic_memory` | jarvisbrain | — | NONE | alpha_conversation_memory | Pattern hole | HIGH |
| `consume_approved_queue_item` | jarvisbrain | — | NONE | alpha_approval_queue | Pattern hole | HIGH |
| `decide_approval` | jarvisbrain | — | NONE | alpha_approval_audit, alpha_approval_queue | Pattern hole | HIGH |
| `enqueue_approval_request` | jarvisbrain | — | NONE | alpha_approval_audit, alpha_approval_queue | Pattern hole | HIGH (writes) |
| `evict_episodic_memory_older_than` | jarvisbrain | — | NONE | alpha_conversation_memory | Pattern hole | HIGH |
| `evict_expired_working_memory` | jarvisbrain | — | NONE | alpha_conversation_memory | Pattern hole | HIGH |
| `expire_pending_approvals` | jarvisbrain | — | NONE | alpha_approval_audit, alpha_approval_queue | Pattern hole | HIGH |
| `forget_memory_by_topic` | jarvisbrain | — | NONE | alpha_conversation_memory | Pattern hole | HIGH |
| `forget_working_memory` | jarvisbrain | — | NONE | alpha_conversation_memory | Pattern hole | HIGH |
| `get_buddy_promotion_candidates` | jarvisbrain | — | NONE | alpha_conversation_memory | Pattern hole | HIGH |
| `list_active_memory_users` | jarvisbrain | — | NONE | alpha_conversation_memory | Pattern hole | HIGH |
| `record_buddy_event` | jarvisbrain | — | NONE | alpha_buddy_events | Pattern hole | HIGH (writes) |
| `record_watchdog_event` | jarvisbrain | — | NONE | alpha_watchdog_events | Pattern hole | HIGH (writes) |
| `run_buddy_memory_maintenance` | jarvisbrain | — | NONE | (none directly — calls other SECDEFs) | OK-by-delegation* | LOW |
| `save_semantic_memory` | jarvisbrain | — | NONE | alpha_semantic_memory | Pattern hole | HIGH (writes) |
| `store_conversation_memory` | jarvisbrain | — | NONE | alpha_conversation_memory | Pattern hole | HIGH (writes) |
| `sync_profile_to_user` | jarvisbrain | — | NONE | (none — operates on alpha_profiles, non-FORCE) | OK-by-table | LOW |

\* `run_buddy_memory_maintenance` body delegates to other SECDEF functions in this list, each of which is itself a pattern hole. So it's not directly broken but inherits HIGH severity transitively.

## 5. Ranked findings

### Severity HIGH — works today via superuser owner, breaks at Slab 7c (BYPASSRLS removal):

**17 of 19 JARVIS SECDEF functions.** Every function listed in §4 marked HIGH operates on a FORCE-RLS table without setting `rls.role`. They work today **only** because `jarvisbrain` (the owner) is `rolsuper=t, rolbypassrls=t`. When Slab 7c removes BYPASSRLS from owners or transfers ownership to a non-superuser role, every one of these will silently begin failing — reads return zero rows, writes raise "new row violates row-level security policy."

The 7 of these that PERFORM WRITES (INSERT/UPDATE/DELETE) are the highest-risk subset, because silent write failures are operationally invisible until downstream queries notice missing rows:

1. `enqueue_approval_request` — writes alpha_approval_audit + alpha_approval_queue (approval gateway hot path).
2. `record_buddy_event` — writes alpha_buddy_events (buddy agent observability).
3. `record_watchdog_event` — writes alpha_watchdog_events (watchdog observability — feeds both background ingest and route `POST /v1/watchdog/event`).
4. `save_semantic_memory` — writes alpha_semantic_memory.
5. `store_conversation_memory` — writes alpha_conversation_memory (every chat message persists via this).
6. `decide_approval` — writes alpha_approval_audit + alpha_approval_queue.
7. `expire_pending_approvals` — writes alpha_approval_queue + alpha_approval_audit (called by buddy agent on a cycle).

### Severity CRITICAL (broken today, owner non-superuser): **0 functions**

The owner of every SECDEF function in the inventory is `jarvisbrain`, who is superuser. No Class A function is silently broken today.

### Severity LOW: 2 functions

- `run_buddy_memory_maintenance` — body inspected; it `RETURN`s the result of `cap_episodic_memory(...) || ... || evict_expired_working_memory()` style composition. It does not itself touch a FORCE-RLS table directly; its callees do, and they are the actual pattern holes. Fix at the callee level fixes the composition.
- `sync_profile_to_user` — operates on `alpha_profiles` which is NOT in the FORCE-RLS set. Out of Class A scope.

## 6. Recommended Phase 2 fleet write order

The fix is a single one-line insertion in each function body — `SELECT set_config('rls.role','platform_admin',true);` (or via `ALTER FUNCTION ... SET rls.role='platform_admin'`). The 17 functions are independent and can be patched in a single migration.

Recommended phasing for review safety:

1. **First migration — approval cluster** (4 functions): `enqueue_approval_request`, `decide_approval`, `consume_approved_queue_item`, `expire_pending_approvals`. Same surface as TD-211; review burden is already amortised; one PR for the approval cluster lets us validate the pattern under live load.
2. **Second migration — memory cluster** (10 functions): `store_conversation_memory`, `save_semantic_memory`, `cap_episodic_memory`, `cap_semantic_memory`, `evict_episodic_memory_older_than`, `evict_expired_working_memory`, `forget_memory_by_topic`, `forget_working_memory`, `bump_memory_access`, `get_buddy_promotion_candidates`, `list_active_memory_users` (count includes the read-only listings that share the same pattern hole). Single hot path; common pattern; one PR.
3. **Third migration — observability cluster** (2 functions + 1 composition): `record_buddy_event`, `record_watchdog_event`, `run_buddy_memory_maintenance`. Smaller cluster; lower review cost as last PR.

Each migration must `ALTER FUNCTION ... SET rls.role = 'platform_admin'` via `proconfig`, **or** add the inline `set_config` at the top of the function body. The marathon's working hypothesis (matching TD-211 hotfix style) is the inline `set_config` route — it's the pattern reviewers have already validated. The `proconfig` route is cleaner but has not been exercised yet in JARVIS production and would require additional validation.

### 6a. Mechanical migration shape

Each function migration follows the same diff template (illustrated with `enqueue_approval_request`):

```sql
CREATE OR REPLACE FUNCTION public.enqueue_approval_request(...)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
BEGIN
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';
+   PERFORM set_config('rls.role', 'platform_admin', true);

    INSERT INTO public.alpha_approval_queue (...) VALUES (...);
    ...
END;
$function$;
```

The `PERFORM` form is preferred over `SELECT` for plpgsql functions returning anything other than a row set — it's idiomatic and matches Postgres docs §43.5.2.

### 6b. Post-migration verification per function

For each migrated function, the same verification recipe applies:

```sql
SET ROLE jarvis_alpha_writer;
BEGIN;
-- exercise the function with realistic args
SELECT public.<function_name>(...);
-- inspect tables touched — count and freshness checks
SELECT count(*) FROM public.<table_touched_1>;
ROLLBACK;
RESET ROLE;
```

If the migration is correct, the function executes successfully under writer-role (no superuser bypass needed) and the inserted/updated rows are visible inside the transaction.

## 7. Risk if Phase 2 is deferred

- **No live impact today.** Owner is superuser; the pattern hole is dormant.
- **Slab 7c regression risk is fleet-wide.** Removing BYPASSRLS from owner roles without first closing the SECDEF holes turns every memory operation, every buddy event, every watchdog event ingest, every approval enqueue, and every approval decision into a silent failure. Cascading consequences: dead conversation memory, no audit trail, watchdog goes blind.
- **Stale comment debt.** `brain/agents/buddy_agent.py:76-77` carries a TD comment saying "wrap in SECDEF when those tables get FORCE RLS" — the SECDEF wrapper exists (`expire_pending_approvals`) but is itself a pattern hole. Comment is misleading; fix erases the confusion.

## 8. Open questions for Ken

1. **`proconfig` route vs inline `set_config`?** Phase 2 can either set `rls.role=platform_admin` per-function via `ALTER FUNCTION ... SET rls.role=platform_admin` (cleaner, single line, applies even to recursive calls) or via inline `SELECT set_config('rls.role','platform_admin',true)` at function body top (matches TD-211 hotfix; reviewer-familiar; pattern is validated). Recommend the inline route for review continuity; flag the proconfig option as a possible cleanup later.
2. **Should Phase 2 also handle `run_buddy_memory_maintenance` body?** It composes callees that all get fixed, so it becomes transitively-correct. But adding an explicit set_config at the composition's top is cheap and makes the function self-documenting. Leave it as-is, or insert defensive set_config?
3. **Are there SECDEF functions outside the `public` schema?** This audit only covered `pronamespace='public'::regnamespace`. The `pgaudit` extension's SECDEFs live in `public` and were skipped explicitly. If JARVIS owns any other schemas (e.g. `internal_audit`, `vault_sec`) those need their own pass. Quick check shows the schema list is `public, pgaudit, jarvis_audit (if exists)` — confirm with a follow-up grep.
4. **Slab 7c sequencing.** This audit assumes Phase 2 closes the holes BEFORE Slab 7c removes BYPASSRLS. If the order reverses, the fleet breaks. Marathon assumed this order; please confirm or file a sequencing constraint.

## 9. Cross-reference: TD-211 caller fix

The TD-211 hotfix landed in `brain/middleware/approval.py:151-155` and explicitly does **caller-side** `set_config('rls.role','platform_admin',true)` before the read against `alpha_approval_queue`. This Phase 1a audit shows the corresponding SECDEF function `consume_approved_queue_item` is still a Class A hole on the function side. Today this is fine — the caller-side fix is sufficient because Brain is running as `jarvis_alpha_writer` and the writer-role connection enters the SECDEF via the wrapper's `SECURITY DEFINER` switch into `jarvisbrain`'s context (superuser, bypass). The Class A fix in Phase 2 makes the function self-sufficient; the TD-211 caller-side fix then becomes belt-and-suspenders rather than the load-bearing layer.

## 10. Artifacts

- Raw inventory + function bodies dumped to `/tmp/secdef_bodies.txt` on Sandbox during audit (transient; recreate via the queries in §2-§3).
- This document.
- Companion: `DISCOVERY_2026-05-11_slab4_phase1b_caller_audit.md`.
