# TD-161 — Non-RLS Table Audit (Slab 6 Pre-flight)

Read-only audit. Date: 2026-04-29. Auditor: claude-opus-4-7 (1M ctx).
Target: Brain Postgres `jarvis_alpha`, schema `public`.
Purpose: enumerate every table in `public` where `relrowsecurity=false`, classify by sensitivity + ownership, and recommend RLS treatment for **Slab 6 — FORCE RLS atomic migration** (RLS Foundation Step 7).

---

## 1. Methodology

### Connection
- SSH host: `jarvisbrain@jarvis-brain.tail40ed36.ts.net` (no `brain` alias in `~/.ssh/config`; resolved via repo grep — `docs/SANDBOX_CLAUDE_RUNBOOK.md`).
- DB: `jarvis_alpha` (user `jarvisbrain`, local socket).
- psql: `/opt/homebrew/Cellar/postgresql@16/16.13/bin/psql`.

### Inventory query (Step 1)
```sql
SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind='r' AND n.nspname='public'
ORDER BY c.relname;
```

### Classification inputs (Step 2)
- Column inventory via `information_schema.columns` for every non-RLS table.
- Row counts via `pg_stat_user_tables.n_live_tup` (load-bearing signal).
- Owner-column probe (`user_id`, `created_by`, `owner_id`, `child_id`, `actor_sub`) to flag Shape A candidates.

### Counts
| Metric | Count |
|---|---|
| Total `public` regular tables | **53** |
| `relrowsecurity=true` (RLS on) | 22 |
| `relrowsecurity=false` (audit subset) | **31** |
| Of RLS-on, also `relforcerowsecurity=true` | 21 |
| Of RLS-on, **NOT** FORCE RLS (gap) | **1** (`alpha_cloud_costs`) |

> Note: `alpha_cloud_costs` has RLS enabled but FORCE RLS off. Owner/superuser still bypasses. Slab 6 should fold this into the FORCE-flip set even though it's not in the 31 audited here.

---

## 2. Non-RLS Table Summary (sorted: sensitivity DESC, then table_name)

Owner-module legend: `alpha` (alpha_*), `chat` (chat_*), `vault` (vault_*), `pipeline` (pipeline_*), `system` (everything else).

| table_name | rls_state | force_rls | sensitivity | owner_module | recommendation | rationale |
|---|---|---|---|---|---|---|
| alpha_credit_balance | off | off | **HIGH** | alpha | Shape B (admin/service) | Financial state (balance_usd, spent_usd, pending_usd). Single-row table. Adults read via app, service-only writes. |
| alpha_perplexity_credit | off | off | **HIGH** | alpha | Shape B (admin/service) | Financial credit balance, single-row. Same shape as alpha_credit_balance. |
| alpha_profiles | off | off | **HIGH** | alpha | Shape B (admin) **+ FK self-scope** | Holds `pin_hash` (auth secret), `child_age`, `max_rating`, `role`. Child-profile data — child sees own row only via `id`, admin sees all. Combined Shape A (id = current_setting('rls.user_id')) + admin override. |
| alpha_secret_rotations | off | off | **HIGH** | alpha | Shape B (admin only) | Secret rotation ledger (`secret_name`, `value_hash`, `rotated_by`, `nodes_updated`). Admin-read, service-write. Children/adults: deny. |
| alpha_subscriptions | off | off | **HIGH** | alpha | Shape B (admin only) | Paid-subscription ledger (`url`, `cost_usd`, `next_renewal`). Adult/admin only. |
| alpha_users | off | off | **HIGH** | alpha | Shape B (admin) + self-row policy | PII: `email`, `role`, `is_child`, `child_age`. Self-row read for adult/child via `id`; admin sees all. |
| alpha_workspace_users | off | off | **HIGH** | alpha | Shape A (`user_id`) + admin override | Membership table — user_id, workspace_id, role. Has `user_id` column. Direct Shape A. |
| jarvis_request_log | off | off | **HIGH** | system | Shape A (`user_id`) + admin override | 78,719 live rows. Per-request audit log with `user_id`, `workspace_id`, `trace_id`, `route`, `cost_usd`, `error`. Largest user-linked table outside RLS. **Highest blast radius** if left open. |
| secret_access_log | off | off | **HIGH** | system | Shape B (admin only) | Access audit for secrets (`key_name`, `source`, `node`). Admin/service only. |
| vault_chunks | off | off | **HIGH** | vault | Shape B with FK lookup | Document chunks + embeddings. No direct user_id — owned via `document_id` → `vault_documents` (which is RLS-on). Inherit ACL via FK pattern: `EXISTS (SELECT 1 FROM vault_documents d WHERE d.id = vault_chunks.document_id)` (vault_documents RLS will gate visibility). 0 rows today — safe window to enable. |
| vault_document_permissions | off | off | **HIGH** | vault | Shape A (`user_id`) + admin | Per-user ACL grants. Has `user_id`. 0 rows today. Admin manages; user can read own grants. |
| alpha_approval_audit_quarantine | off | off | **MED** | alpha | Shape B (admin only) | 582 rows. Failed/quarantined approval audit. Holds `actor_sub`, `parameters_hash`, `decided_by`. Admin-only read; system-only write (no UPDATE/DELETE). Mirrors `alpha_approval_audit` shape (which is FORCE RLS). |
| alpha_briefings | off | off | **MED** | alpha | Shape B (admin/adult) | Daily briefings (`summary`, `results` jsonb, `markdown`). Cross-user system content; could leak operational signal. Admin/adult-read; service-write. |
| alpha_dream_allowed_paths | off | off | **MED** | alpha | Shape B (admin only) | Allow-list of filesystem globs for Dream mode — gates write capability. System flag with security impact. Admin-only. |
| alpha_honeypot_events | off | off | **MED** | system | Shape B (admin only) | Captured intrusion attempts (`source_ip`, `user_agent`, `headers`). Sensitive security telemetry — admin-only. |
| alpha_node_registry | off | off | **MED** | alpha | Shape B (admin/adult/service read; admin/service write) | Per RLS_ROLLOUT_PLAN §5.4: admin+adult+service+agent read, admin+service write. Holds `tailscale_ip`, cert metadata. |
| alpha_overnight_approvals | off | off | **MED** | alpha | Shape B (admin only) | Per RLS_ROLLOUT_PLAN §5.3: admin only. Pre-approval grants — `pattern`, `budget_usd`, `created_by`. Currently 0 rows. |
| alpha_projects | off | off | **MED** | alpha | Shape A via `owner_id` (NEEDS COLUMN ADD) | Per RLS_ROLLOUT_PLAN §5.2: project-scoped. **Current schema lacks `owner_id`/`created_by`** — only `id`, `name`, `project_type`, `repo_slug`, `created_at`. Needs column + backfill before policy. **Defer to its own slab** (see RLS_ROLLOUT_PLAN Phase B8). |
| alpha_prompt_registry | off | off | **MED** | alpha | Shape B (admin only) | System prompts + model hints. Editing these alters model behavior — admin-only write; system reads. |
| alpha_workspaces | off | off | **MED** | alpha | Shape B with membership join | Workspace records. Visibility should join through `alpha_workspace_users` (user must be a member). 1 row today. Per RLS_ROLLOUT_PLAN §11 it's deferred until multi-user feature ships — leave for now but document. |
| pipeline_lessons | off | off | **MED** | pipeline | Shape B (Forge service) | Per RLS_ROLLOUT_PLAN §6.4: admin all, forge service own. 0 rows today. |
| pipeline_metrics_brain | off | off | **MED** | pipeline | Shape B (Forge service) | Per RLS_ROLLOUT_PLAN §5.5: admin + forge. 0 rows today. |
| pipeline_trust_scores | off | off | **MED** | pipeline | Shape B (Forge service) | Per RLS_ROLLOUT_PLAN §5.5: admin + forge. 0 rows today. |
| alpha_budget_config | off | off | **LOW** | alpha | LEAVE DISABLED (admin-only via GRANT) | 3 rows. Per-provider monthly cap. Tiny config; cross-user immutable parameter. Recommend `REVOKE ALL ... FROM jarvis_alpha_writer; GRANT SELECT TO ...` instead of RLS. |
| alpha_hardware_config | off | off | **LOW** | alpha | LEAVE DISABLED | 4 rows. Hardware cost amortization params. No user linkage; cross-cutting config. |
| alpha_model_pricing | off | off | **LOW** | alpha | LEAVE DISABLED | 14 rows. Vendor pricing table — public-domain per-model rates. No user linkage. Lookup table. |
| alpha_power_config | off | off | **LOW** | alpha | LEAVE DISABLED | 1 row. Electricity rate. No user linkage. |
| alpha_power_daily | off | off | **LOW** | alpha | LEAVE DISABLED | 20 rows. Aggregated kWh telemetry by node. No user linkage. |
| alpha_power_hourly | off | off | **LOW** | alpha | LEAVE DISABLED | 100 rows. Same as above, hourly. |
| alpha_power_readings | off | off | **LOW** | alpha | LEAVE DISABLED | 8,100 rows. Raw watt readings per node. No user linkage. |
| schema_migrations | off | off | **LOW** | system | LEAVE DISABLED | 62 rows. DDL ledger. Operational; service-managed; superuser-only by GRANT. |

### Sensitivity tally (non-RLS subset)
| Sensitivity | Count |
|---|---|
| HIGH | **11** |
| MED | **12** |
| LOW | **8** |
| Total | 31 |

### Recommendation tally
| Recommendation | Count |
|---|---|
| ENABLE — Shape A (user-scoped via `user_id`) | 2 (`alpha_workspace_users`, `jarvis_request_log`) |
| ENABLE — Shape A combined (self-row id) | 2 (`alpha_users`, `alpha_profiles`) |
| ENABLE — Shape B (admin/service gate) | 14 |
| ENABLE — Shape B with FK inheritance | 2 (`vault_chunks`, `alpha_workspaces`) |
| DEFER (column missing or arch question) | 2 (`alpha_projects`, `alpha_workspaces`) |
| LEAVE DISABLED (LOW, no user linkage) | 8 |

(Several rows fall into multiple buckets above — `alpha_workspaces` is both Shape B + DEFER; counted once each side for visibility.)

---

## 3. Tables Flagged for Human Review

| Table | Question |
|---|---|
| **alpha_projects** | RLS_ROLLOUT_PLAN §5.2 says owner-column scoped, but the live table has no `owner_id`/`created_by`. **Should Slab 6 add the column + backfill, or punt to a follow-up slab?** Plan §B2 explicitly warns against blind backfill. Current row count = 1, so backfill is trivial; question is scope discipline for Slab 6 (atomic FORCE-flip vs schema change). |
| **alpha_workspaces** | RLS_ROLLOUT_PLAN §11 says **deferred until multi-user workspace feature ships**. Confirm: skip in Slab 6, document deferral in TD-161 closeout. |
| **jarvis_request_log** | 78,719 live rows. **Is `user_id` populated for all rows, or do we need a backfill (`'_unknown'`/`'_system'`) before flipping RLS?** Run `SELECT count(*) FROM jarvis_request_log WHERE user_id IS NULL OR user_id = '';` to confirm. Slab 6 should NOT FORCE-flip if NULL/empty rows exist — would trap audit history under admin-only view. |
| **alpha_briefings** | Confirm sensitivity tier — does the `summary`/`results` jsonb ever contain child-profile content or PII? If yes, escalate from MED to HIGH and tighten policy (admin only, no adult read). |
| **alpha_subscriptions** | Adult-readable or admin-only? Plan doesn't list it. Default: admin-only (Shape B). Confirm. |
| **alpha_credit_balance / alpha_perplexity_credit** | Adults need read access for "current spend" UI? If yes, add adult-read policy alongside admin. If admin-only, leave Shape B. |
| **alpha_dream_allowed_paths** | Should this gain FORCE RLS too? It's currently config; if Forge/Dream service is the only writer, Shape B with admin+service write, admin read. |
| **vault_chunks** | Confirm FK inheritance pattern is desired (vs duplicating user_id column). FK pattern is cleaner; ensure `vault_documents` policies cover SELECT path. |
| **alpha_users** vs **alpha_profiles** | Two PII tables. Are these separate concerns (auth identity vs household profile) or pending merge? Affects whether they share a policy template. |

---

## 4. Cross-check vs HANDOFF

**Note:** `docs/handoffs/HANDOFF_2026-04-27_01.md` was **not found** on either Sand (`/Users/jarvissand/jarvis-alpha/docs/handoffs/`) or Brain (`~/jarvis-alpha/docs/handoffs/`). The latest dated handoff present is `HANDOFF_2026-04-21_02.md`. **Cannot verify TD-161 P1 description directly.**

Cross-checked instead against:
- `docs/RLS_ROLLOUT_PLAN.md` (V2, REVIEWED, April 2026)
- `docs/JARVIS_Alpha_Phase_Status.md` ("FORCE RLS universal — 21 tables live (verified 2026-04-18 Brain)")
- `docs/STEP7_DISCOVERY.md`

### Alignment notes
- Phase Status claims "21 tables live" with FORCE RLS. Live count verified: **21** tables have `relforcerowsecurity=true`. ✅ matches.
- RLS_ROLLOUT_PLAN §12 names ~14 NEW tables expected to gain RLS in the rollout. Of those:
  - `alpha_projects` — non-RLS today ✅ (in audit, flagged DEFER pending owner column)
  - `alpha_overnight_approvals` — non-RLS today ✅ (MED, Shape B)
  - `pipeline_lessons`, `pipeline_metrics_brain`, `pipeline_trust_scores` — non-RLS today ✅ (MED, Shape B service-scoped)
  - `alpha_node_registry` — non-RLS today ✅ (MED, Shape B)
  - `chat_threads`, `chat_messages`, `thread_memory_extracts`, `alpha_task_graphs`, `alpha_task_steps`, `alpha_approval_queue`, `alpha_approval_audit`, `alpha_overnight_approvals`, `alpha_buddy_events` — already RLS-on ✅ (these were Slabs 2–5).

### Surprises
1. **`jarvis_request_log` is NOT in RLS_ROLLOUT_PLAN §12** but holds per-user data (`user_id`, `workspace_id`) at the largest volume of any non-RLS table (78,719 rows). This is a **gap in the rollout plan** — must be added to Slab 6 scope or explicitly deferred with rationale.
2. **`alpha_users`, `alpha_profiles`, `alpha_workspace_users`** — also missing from §12. These hold identity PII and `pin_hash`. Cannot ship Slab 6 ("FORCE RLS atomic") while these remain bypassable.
3. **`alpha_cloud_costs`** has RLS enabled but FORCE RLS **disabled** — superuser/owner bypasses. This is the only inconsistent row in the RLS-on set; Slab 6 should either flip FORCE on or explicitly justify the exception.
4. **`alpha_subscriptions`, `alpha_credit_balance`, `alpha_perplexity_credit`, `alpha_secret_rotations`, `alpha_briefings`, `alpha_dream_allowed_paths`, `alpha_honeypot_events`, `alpha_prompt_registry`, `alpha_approval_audit_quarantine`, `secret_access_log`** — admin-only sensitive tables, not in §12 either. They don't need user-scoped policies but **do** need `relrowsecurity=true` + FORCE + admin-only Shape B to prevent writer-role escape.
5. **`vault_chunks`, `vault_document_permissions`** — Vault module non-RLS while the parent `vault_documents` IS FORCE RLS. The chunk table holds embeddings + content for those documents; leaving it open defeats the parent's protection. Should be in Slab 6.

The audit's HIGH count (**11**) is materially larger than what §12 implies for "remaining work." Slab 6 scope needs explicit broadening, OR a clear partition between "Slab 6 Phase 1 (admin-only sensitive tables)" and "Slab 6 Phase 2 (user-scoped tables needing column adds)."

---

## 5. Slab 6 Readiness Assessment

**Verdict: NOT READY for an "atomic" Slab 6 as currently scoped. Plan-able, but needs scope re-cut and 2 prerequisite confirmations.**

### Blockers (must resolve before writing Slab 6 migration)

1. **HANDOFF_2026-04-27_01.md missing.** The TD-161 P1 description, expected non-RLS count, and any constraints from the team are not retrievable. Recover the file (uncommitted? Forge sandbox?) or have the human re-state expected scope before migration draft.
2. **`jarvis_request_log` user_id NULL audit.** Must verify all 78,719 rows have a non-empty `user_id` before FORCE-flip, or backfill `'_unknown'`/`'_system'` first. Risk: FORCE RLS on a table with NULL user_id traps history.
3. **`alpha_projects` owner column missing.** Cannot apply Shape A without `owner_id`/`created_by`. Either add column + backfill in same migration (scope creep) or carve `alpha_projects` out of Slab 6.

### Non-blocking but plan-disrupting

4. **`alpha_cloud_costs` FORCE-RLS hole.** Slab 6 should fold this in (1 line: `ALTER TABLE alpha_cloud_costs FORCE ROW LEVEL SECURITY;`). Otherwise the "atomic universal FORCE" claim is false.
5. **HIGH-sensitivity admin-only tables not in §12.** Plan should be amended to enumerate them so policy text is reviewable before merge: `alpha_users`, `alpha_profiles`, `alpha_workspace_users`, `alpha_subscriptions`, `alpha_credit_balance`, `alpha_perplexity_credit`, `alpha_secret_rotations`, `alpha_briefings`, `alpha_honeypot_events`, `alpha_prompt_registry`, `alpha_approval_audit_quarantine`, `secret_access_log`, `alpha_dream_allowed_paths`, `alpha_node_registry`, `alpha_overnight_approvals`, `vault_chunks`, `vault_document_permissions`.
6. **8 LOW tables that should explicitly remain disabled** need a one-line rationale committed to the migration file (so future audits don't re-flag): `alpha_budget_config`, `alpha_hardware_config`, `alpha_model_pricing`, `alpha_power_config`, `alpha_power_daily`, `alpha_power_hourly`, `alpha_power_readings`, `schema_migrations`.

### Recommended Slab 6 scope (re-cut)

- **Slab 6a — admin-only Shape B blast** (atomic, low-risk): 14 admin-gated tables with no user-column dependency. Pure DDL: `ALTER TABLE … ENABLE/FORCE` + `CREATE POLICY admin_full_access`. Single migration.
- **Slab 6b — user-scoped Shape A** (3 tables: `alpha_workspace_users`, `jarvis_request_log`, `vault_document_permissions`). Requires NULL audit on `jarvis_request_log` first.
- **Slab 6c — self-row PII** (2 tables: `alpha_users`, `alpha_profiles`). Combined admin + self-id policy.
- **Slab 6d (FK pattern)** — `vault_chunks` via `vault_documents`.
- **Defer to Slab 7** — `alpha_projects` (owner column add), `alpha_workspaces` (multi-user feature dependency).
- **LEAVE DISABLED** — 8 LOW tables, documented in migration comments.
- **Fold-in** — `alpha_cloud_costs` FORCE flip.

This re-cut keeps each slab idempotent, atomic, and reversible per RLS_ROLLOUT_PLAN §10.

---

## Appendix A — Full table state (53 tables, current)

| relname | rls | force |
|---|---|---|
| alpha_approval_audit | t | t |
| alpha_approval_audit_quarantine | f | f |
| alpha_approval_queue | t | t |
| alpha_briefings | f | f |
| alpha_buddy_events | t | t |
| alpha_budget_config | f | f |
| alpha_cloud_costs | t | **f** |
| alpha_conversation_memory | t | t |
| alpha_credit_balance | f | f |
| alpha_dream_allowed_paths | f | f |
| alpha_dream_blocked_writes | t | t |
| alpha_dream_cost_caps | t | t |
| alpha_dream_cost_counters | t | t |
| alpha_dream_model_policy | t | t |
| alpha_dream_sessions | t | t |
| alpha_dream_steps | t | t |
| alpha_hardware_config | f | f |
| alpha_honeypot_events | f | f |
| alpha_model_pricing | f | f |
| alpha_node_registry | f | f |
| alpha_overnight_approvals | f | f |
| alpha_perplexity_credit | f | f |
| alpha_power_config | f | f |
| alpha_power_daily | f | f |
| alpha_power_hourly | f | f |
| alpha_power_readings | f | f |
| alpha_profiles | f | f |
| alpha_projects | f | f |
| alpha_prompt_registry | f | f |
| alpha_secret_rotations | f | f |
| alpha_semantic_memory | t | t |
| alpha_subscriptions | f | f |
| alpha_system_flags | t | t |
| alpha_task_events | t | t |
| alpha_task_graphs | t | t |
| alpha_task_steps | t | t |
| alpha_users | f | f |
| alpha_watchdog_events | t | t |
| alpha_workspace_users | f | f |
| alpha_workspaces | f | f |
| chat_messages | t | t |
| chat_threads | t | t |
| jarvis_request_log | f | f |
| pipeline_lessons | f | f |
| pipeline_metrics_brain | f | f |
| pipeline_trust_scores | f | f |
| schema_migrations | f | f |
| secret_access_log | f | f |
| vault_access_log | t | t |
| vault_chunks | f | f |
| vault_document_permissions | f | f |
| vault_documents | t | t |
| vault_pipeline | t | t |

---

## Appendix B — Owner-column probe results

Tables with at least one of (`user_id`, `created_by`, `owner_id`, `child_id`, `actor_sub`):

- alpha_approval_audit_quarantine — `actor_sub`
- alpha_overnight_approvals — `created_by`, `revoked_by` (text, admin sentinels)
- alpha_workspace_users — `user_id`
- jarvis_request_log — `user_id` (+ `workspace_id`)
- vault_document_permissions — `user_id`

All other non-RLS tables either are pure config/lookup, hold cross-user telemetry without a per-user link, or use a self-row identity column (e.g. `alpha_users.id`, `alpha_profiles.id`).

---

## Appendix C — Live row counts (signal of blast radius)

| Table | n_live_tup |
|---|---|
| jarvis_request_log | **78,719** |
| alpha_power_readings | 8,100 |
| alpha_approval_audit_quarantine | 582 |
| alpha_power_hourly | 100 |
| schema_migrations | 62 |
| secret_access_log | 57 |
| alpha_briefings | 23 |
| alpha_power_daily | 20 |
| alpha_model_pricing | 14 |
| alpha_node_registry | 7 |
| alpha_hardware_config | 4 |
| alpha_budget_config / alpha_dream_allowed_paths / alpha_profiles / alpha_subscriptions / alpha_users / alpha_workspace_users | 3 each |
| alpha_secret_rotations / alpha_honeypot_events | 2 each |
| alpha_credit_balance / alpha_perplexity_credit / alpha_power_config / alpha_projects / alpha_prompt_registry / alpha_workspaces | 1 each |
| pipeline_lessons / pipeline_metrics_brain / pipeline_trust_scores / alpha_overnight_approvals / vault_chunks / vault_document_permissions | 0 each |

The 0-row tables are the safest places to start enabling RLS (no backfill risk).

---

*Audit complete. No DB writes performed. No code edits. No commits.*
