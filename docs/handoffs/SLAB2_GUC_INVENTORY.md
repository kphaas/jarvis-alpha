# SLAB 2 GUC Inventory — RLS Foundation Step 7

**Date:** 2026-04-29
**Scope:** Read-only inventory of every `current_setting(...)` and `set_config(...)` (plus SQL `SET LOCAL`) reference to a custom-namespace GUC across `.py` / `.sql` / `.psql` / `.sh` files in the jarvis-alpha tree.
**Excluded paths:** `.git`, `.venv`, `.deprecated`, `dist`, `node_modules`, `__pycache__`.
**Method:** ripgrep 14.1.1 with the regexes specified in the Slab 2 spec.

---

## Section 1 — Headline counts

| metric | memory_claim | observed | delta | notes |
|---|---|---|---|---|
| `jarvis.*` reads (`current_setting`) | 84 | **84** | 0 | Includes 16 in dump artifacts (`db/postgres_schema.sql` + 2 `db/baselines/*.sql`); 68 in live code. |
| `jarvis.*` writes (`set_config` + `SET LOCAL`) | 17 | **21** | +4 | Memory counted only `set_config()` calls; 4 `SET LOCAL jarvis.role = …` migration headers were omitted. All 17 `set_config` calls confirmed. |
| `app.*` reads (`current_setting`) | 58 | **58** | 0 | Includes 28 in dump artifacts; 30 in live migrations. |
| `app.*` writes (`set_config`) | not stated | **3** | n/a | All in `brain/db/rls.py` (`app.user_id`, `app.max_rating`, `app.workspace_id`). |
| Python files writing `jarvis.*` | 9 | **9** | 0 | Exact match with memory. |
| `rls.*` reads | not stated | **15** | n/a | Includes 8 in dump artifacts; 7 in live code (`015_chat_rls_fix.sql`, `012_watchdog_events.sql`, `db/alembic/versions/003_chat_threads.py`). |
| `rls.*` writes | not stated | **1** | n/a | `scripts/smoke_5d1_watchdog_agent.sh:61`. |
| `pgaudit.*` reads | not stated | **4** | n/a | All in `brain/db/migrations/20260429_170000_install_pgaudit.sql` (third-party extension; **must not** be migrated to `rls.*`). |
| **TOTAL custom-GUC reads** | — | **161** | — | jarvis 84 + app 58 + rls 15 + pgaudit 4 |
| **TOTAL custom-GUC writes** | — | **25** | — | jarvis 17 set_config + 4 SET LOCAL + app 3 + rls 1 |

**Delta explanation — `jarvis.*` writes (+4 vs memory):**
The four extra writes are SQL migration headers added on 2026-04-22 (after the memory snapshot):
- `brain/db/migrations/20260422_120001_alpha_cloud_costs_idempotency_key.sql:3`
- `brain/db/migrations/20260422_120002_alpha_system_flags_halt_severity.sql:3`
- `brain/db/migrations/20260422_120003_alpha_dream_sessions_status_halted.sql:3`
- `brain/db/migrations/20260422_160027_dream_rls_permissive_platform_admin.sql:3`

All four are `SET LOCAL jarvis.role = 'platform_admin';` at the top of forward migrations. The memory regex (`set_config\(...)` only) missed these because they use the SQL `SET LOCAL` form. The Slab 2 spec explicitly counts SQL `SET` statements as writes, so the corrected total is **21**.

**Note on dump artifacts:** `db/postgres_schema.sql`, `db/baselines/baseline_2026-04-07_pre_step7.sql`, and `db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql` are `pg_dump` outputs of a pre-Step-7 database. They reproduce the same policies as the migrations and contribute 44 of the 161 reads. They will be regenerated post-migration; **do not hand-edit**. They are included in headline counts because they match the search regex literally.

---

## Section 2 — Exhaustive line-by-line table

Sorted by file, then line. Type is `R` (read = `current_setting`) or `W` (write = `set_config` or SQL `SET LOCAL`).

| file | line | type | namespace.name | full_call |
|---|---|---|---|---|
| brain/db/migrations/003_memory_tiers.sql | 36 | R | jarvis.current_user | `current_setting('jarvis.current_user')` |
| brain/db/migrations/003_memory_tiers.sql | 37 | R | jarvis.is_admin | `current_setting('jarvis.is_admin', true)` |
| brain/db/migrations/006_task_graphs.sql | 64 | R | jarvis.current_user | `current_setting('jarvis.current_user', TRUE)` |
| brain/db/migrations/006_task_graphs.sql | 65 | R | jarvis.role | `current_setting('jarvis.role', TRUE)` |
| brain/db/migrations/006_task_graphs.sql | 72 | R | jarvis.current_user | `current_setting('jarvis.current_user', TRUE)` |
| brain/db/migrations/006_task_graphs.sql | 73 | R | jarvis.role | `current_setting('jarvis.role', TRUE)` |
| brain/db/migrations/008b_task_events.sql | 35 | R | jarvis.current_user | `current_setting('jarvis.current_user', TRUE)` |
| brain/db/migrations/009_child_profiles.sql | 53 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/009_child_profiles.sql | 54 | R | app.profile_id | `current_setting('app.profile_id', true)` |
| brain/db/migrations/009_child_profiles.sql | 61 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/009_child_profiles.sql | 64 | R | app.profile_id | `current_setting('app.profile_id', true)` |
| brain/db/migrations/009_child_profiles.sql | 72 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/009_child_profiles.sql | 73 | R | app.max_rating | `current_setting('app.max_rating', true)` |
| brain/db/migrations/009_child_profiles.sql | 80 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/009_child_profiles.sql | 81 | R | app.max_rating | `current_setting('app.max_rating', true)` |
| brain/db/migrations/009_child_profiles.sql | 88 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/009_child_profiles.sql | 95 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/009_child_profiles.sql | 102 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/009_child_profiles.sql | 109 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/012_watchdog_events.sql | 53 | R | rls.user_id | `current_setting('rls.user_id', true)` |
| brain/db/migrations/014_vault_rls_v1.sql | 47 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/014_vault_rls_v1.sql | 50 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/014_vault_rls_v1.sql | 57 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/014_vault_rls_v1.sql | 58 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/014_vault_rls_v1.sql | 66 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/014_vault_rls_v1.sql | 67 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/014_vault_rls_v1.sql | 75 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/014_vault_rls_v1.sql | 76 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/015_chat_rls_fix.sql | 13 | R | rls.user_id | `current_setting('rls.user_id', true)` |
| brain/db/migrations/015_chat_rls_fix.sql | 14 | R | rls.user_id | `current_setting('rls.user_id', true)` |
| brain/db/migrations/015_chat_rls_fix.sql | 19 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/015_chat_rls_fix.sql | 20 | R | app.profile_id | `current_setting('app.profile_id', true)` |
| brain/db/migrations/015_chat_rls_fix.sql | 23 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/015_chat_rls_fix.sql | 24 | R | app.profile_id | `current_setting('app.profile_id', true)` |
| brain/db/migrations/015_chat_rls_fix.sql | 36 | R | rls.user_id | `current_setting('rls.user_id', true)` |
| brain/db/migrations/015_chat_rls_fix.sql | 42 | R | rls.user_id | `current_setting('rls.user_id', true)` |
| brain/db/migrations/015_chat_rls_fix.sql | 49 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/015_chat_rls_fix.sql | 52 | R | app.profile_id | `current_setting('app.profile_id', true)` |
| brain/db/migrations/015_chat_rls_fix.sql | 56 | R | app.profile_role | `current_setting('app.profile_role', true)` |
| brain/db/migrations/015_chat_rls_fix.sql | 59 | R | app.profile_id | `current_setting('app.profile_id', true)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 107 | R | jarvis.role | `current_setting('jarvis.role', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 115 | R | jarvis.role | `current_setting('jarvis.role', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 123 | R | jarvis.role | `current_setting('jarvis.role', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 131 | R | jarvis.current_user | `current_setting('jarvis.current_user', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 132 | R | jarvis.current_user | `current_setting('jarvis.current_user', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 137 | R | jarvis.role | `current_setting('jarvis.role', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 138 | R | jarvis.current_user | `current_setting('jarvis.current_user', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 141 | R | jarvis.role | `current_setting('jarvis.role', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 142 | R | jarvis.current_user | `current_setting('jarvis.current_user', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 154 | R | jarvis.current_user | `current_setting('jarvis.current_user', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 158 | R | jarvis.current_user | `current_setting('jarvis.current_user', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 164 | R | jarvis.role | `current_setting('jarvis.role', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 167 | R | jarvis.current_user | `current_setting('jarvis.current_user', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 171 | R | jarvis.role | `current_setting('jarvis.role', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 174 | R | jarvis.current_user | `current_setting('jarvis.current_user', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 182 | R | jarvis.role | `current_setting('jarvis.role', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 183 | R | app.max_rating | `current_setting('app.max_rating', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 196 | R | jarvis.role | `current_setting('jarvis.role', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 199 | R | jarvis.role | `current_setting('jarvis.role', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 206 | R | jarvis.role | `current_setting('jarvis.role', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 210 | R | jarvis.role | `current_setting('jarvis.role', TRUE)` |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 214 | R | jarvis.role | `current_setting('jarvis.role', TRUE)` |
| brain/db/migrations/20260414_140000_approval_rls.sql | 18 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260414_140000_approval_rls.sql | 19 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260414_140000_approval_rls.sql | 24 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260414_140000_approval_rls.sql | 25 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260414_150000_force_rls_stage6cd.sql | 31 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260414_150000_force_rls_stage6cd.sql | 32 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260414_160000_fix_semantic_isolation.sql | 12 | R | jarvis.current_user | `current_setting('jarvis.current_user', true)` |
| brain/db/migrations/20260414_160000_fix_semantic_isolation.sql | 13 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260414_180000_child_rls_policies.sql | 12 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260414_180000_child_rls_policies.sql | 15 | R | app.max_rating | `current_setting('app.max_rating', true)` |
| brain/db/migrations/20260414_180000_child_rls_policies.sql | 25 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260414_180000_child_rls_policies.sql | 26 | R | jarvis.current_user | `current_setting('jarvis.current_user', true)` |
| brain/db/migrations/20260414_180000_child_rls_policies.sql | 35 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260414_180000_child_rls_policies.sql | 39 | R | jarvis.current_user | `current_setting('jarvis.current_user', true)` |
| brain/db/migrations/20260414_180000_child_rls_policies.sql | 49 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260414_180000_child_rls_policies.sql | 50 | R | jarvis.current_user | `current_setting('jarvis.current_user', true)` |
| brain/db/migrations/20260414_180000_child_rls_policies.sql | 59 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260414_180000_child_rls_policies.sql | 60 | R | jarvis.current_user | `current_setting('jarvis.current_user', true)` |
| brain/db/migrations/20260416_080001_audit_stream_view.sql | 179 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260416_080001_audit_stream_view.sql | 182 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260416_080001_audit_stream_view.sql | 185 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260416_080001_audit_stream_view.sql | 188 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260416_170000_cloud_costs_rls.sql | 12 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260416_170000_cloud_costs_rls.sql | 13 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260417_120000_dream_invariants.sql | 36 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260417_120000_dream_invariants.sql | 37 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260417_120100_dream_cost_caps.sql | 40 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260417_120100_dream_cost_caps.sql | 41 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260417_120100_dream_cost_caps.sql | 45 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260417_120100_dream_cost_caps.sql | 46 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260417_130000_system_flags.sql | 21 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260417_130000_system_flags.sql | 22 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260417_131000_dream_model_policy.sql | 38 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260417_131000_dream_model_policy.sql | 39 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260422_120001_alpha_cloud_costs_idempotency_key.sql | 3 | W | jarvis.role | `SET LOCAL jarvis.role = 'platform_admin';` |
| brain/db/migrations/20260422_120002_alpha_system_flags_halt_severity.sql | 3 | W | jarvis.role | `SET LOCAL jarvis.role = 'platform_admin';` |
| brain/db/migrations/20260422_120003_alpha_dream_sessions_status_halted.sql | 3 | W | jarvis.role | `SET LOCAL jarvis.role = 'platform_admin';` |
| brain/db/migrations/20260422_160027_dream_rls_permissive_platform_admin.sql | 3 | W | jarvis.role | `SET LOCAL jarvis.role = 'platform_admin';` |
| brain/db/migrations/20260422_160027_dream_rls_permissive_platform_admin.sql | 10 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260422_160027_dream_rls_permissive_platform_admin.sql | 11 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260422_160027_dream_rls_permissive_platform_admin.sql | 21 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260422_160027_dream_rls_permissive_platform_admin.sql | 22 | R | jarvis.role | `current_setting('jarvis.role', true)` |
| brain/db/migrations/20260429_170000_install_pgaudit.sql | 69 | R | pgaudit.log | `current_setting('pgaudit.log')` |
| brain/db/migrations/20260429_170000_install_pgaudit.sql | 70 | R | pgaudit.log_relation | `current_setting('pgaudit.log_relation')` |
| brain/db/migrations/20260429_170000_install_pgaudit.sql | 71 | R | pgaudit.log_parameter | `current_setting('pgaudit.log_parameter')` |
| brain/db/migrations/20260429_170000_install_pgaudit.sql | 72 | R | pgaudit.log_statement | `current_setting('pgaudit.log_statement')` |
| brain/db/rls.py | 86 | W | jarvis.current_user | `set_config('jarvis.current_user', $1, true)` |
| brain/db/rls.py | 89 | W | jarvis.role | `set_config('jarvis.role', $1, true)` |
| brain/db/rls.py | 92 | W | app.user_id | `set_config('app.user_id', $1, true)` |
| brain/db/rls.py | 95 | W | app.max_rating | `set_config('app.max_rating', $1, true)` |
| brain/db/rls.py | 98 | W | app.workspace_id | `set_config('app.workspace_id', $1, true)` |
| brain/db/schema.sql | 149 | R | jarvis.current_user | `current_setting('jarvis.current_user', true)` |
| brain/dream/_db.py | 34 | W | jarvis.current_user | `set_config('jarvis.current_user', $1, true)` |
| brain/dream/_db.py | 36 | W | jarvis.role | `set_config('jarvis.role', $1, true)` |
| brain/routes/dev.py | 55 | W | jarvis.current_user | `set_config('jarvis.current_user', $1, true)` |
| brain/routes/dev.py | 59 | W | jarvis.role | `set_config('jarvis.role', $1, true)` |
| brain/routes/dev.py | 274 | W | jarvis.current_user | `set_config('jarvis.current_user', $1, true)` |
| brain/routes/dev.py | 278 | W | jarvis.role | `set_config('jarvis.role', $1, true)` |
| brain/routes/dream_planning.py | 76 | W | jarvis.role | `set_config('jarvis.role', 'platform_admin', true)` |
| brain/routes/internal_cost.py | 97 | W | jarvis.role | `set_config('jarvis.role', 'platform_admin', true)` |
| brain/services/dream_cost_cap_service.py | 46 | W | jarvis.role | `set_config('jarvis.role', 'platform_admin', true)` |
| brain/services/dream_cost_cap_service.py | 128 | W | jarvis.role | `set_config('jarvis.role', 'platform_admin', true)` |
| brain/services/dream_invariant_checker.py | 145 | W | jarvis.role | `set_config('jarvis.role', 'platform_admin', true)` |
| brain/services/dream_invariant_checker.py | 306 | W | jarvis.role | `set_config('jarvis.role', 'platform_admin', true)` |
| brain/tasks/executor.py | 46 | W | jarvis.current_user | `set_config('jarvis.current_user', 'platform_admin', true)` |
| brain/tasks/executor.py | 48 | W | jarvis.role | `set_config('jarvis.role', 'platform_admin', true)` |
| db/alembic/versions/001_taskgraph.py | 95 | R | jarvis.current_user | `current_setting('jarvis.current_user', true)` |
| db/alembic/versions/001_taskgraph.py | 102 | R | jarvis.current_user | `current_setting('jarvis.current_user', true)` |
| db/alembic/versions/003_chat_threads.py | 58 | R | rls.user_id | `current_setting('rls.user_id', true)` |
| db/alembic/versions/003_chat_threads.py | 65 | R | rls.user_id | `current_setting('rls.user_id', true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2557 | R | jarvis.current_user | `current_setting('jarvis.current_user'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2557 | R | jarvis.role | `current_setting('jarvis.role'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2602 | R | rls.user_id | `current_setting('rls.user_id'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2604 | R | rls.user_id | `current_setting('rls.user_id'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2617 | R | rls.user_id | `current_setting('rls.user_id'::text, true)` (×2) |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2624 | R | app.profile_role / app.max_rating | `current_setting('app.profile_role'::text, true)` + `current_setting('app.max_rating'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2631 | R | app.profile_role | `current_setting('app.profile_role'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2638 | R | app.profile_role | `current_setting('app.profile_role'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2645 | R | app.profile_role / app.max_rating | `current_setting('app.profile_role'::text, true)` + `current_setting('app.max_rating'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2652 | R | app.profile_role | `current_setting('app.profile_role'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2659 | R | app.profile_role | `current_setting('app.profile_role'::text, true)` (×2) |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2661 | R | app.profile_id | `current_setting('app.profile_id'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2663 | R | app.profile_id | `current_setting('app.profile_id'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2670 | R | app.profile_role | `current_setting('app.profile_role'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2677 | R | app.profile_role / app.profile_id | `current_setting('app.profile_role'::text, true)` + `current_setting('app.profile_id'::text, true)` (USING + WITH CHECK = 4 hits on this line) |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2684 | R | jarvis.current_user / jarvis.is_admin | `current_setting('jarvis.current_user'::text)` + `current_setting('jarvis.is_admin'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2691 | R | jarvis.role / jarvis.current_user | `current_setting('jarvis.role'::text, true)` + `current_setting('jarvis.current_user'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2698 | R | jarvis.current_user / jarvis.role | `current_setting('jarvis.current_user'::text, true)` + `current_setting('jarvis.role'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2705 | R | jarvis.current_user / jarvis.role | `current_setting('jarvis.current_user'::text, true)` + `current_setting('jarvis.role'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2718 | R | app.profile_role | `current_setting('app.profile_role'::text, true)` (×2) |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2731 | R | app.profile_role | `current_setting('app.profile_role'::text, true)` (×2) |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2738 | R | app.profile_role | `current_setting('app.profile_role'::text, true)` (×2) |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2751 | R | app.profile_role | `current_setting('app.profile_role'::text, true)` (×2) |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2765 | R | rls.user_id | `current_setting('rls.user_id'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2731 | R | jarvis.current_user / jarvis.role | (same as `pre_step7.sql` line 2557) |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2776 | R | rls.user_id | `current_setting('rls.user_id'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2778 | R | rls.user_id | `current_setting('rls.user_id'::text, true)` |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2791 | R | rls.user_id | `current_setting('rls.user_id'::text, true)` (×2) |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2798 | R | app.profile_role / app.max_rating | dump duplicate of `pre_step7.sql:2624` |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2805 | R | app.profile_role | dump duplicate |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2812 | R | app.profile_role | dump duplicate |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2819 | R | app.profile_role / app.max_rating | dump duplicate |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2826 | R | app.profile_role | dump duplicate |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2833 | R | app.profile_role | dump duplicate (×2) |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2835 | R | app.profile_id | dump duplicate |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2837 | R | app.profile_id | dump duplicate |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2844 | R | app.profile_role | dump duplicate |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2851 | R | app.profile_role / app.profile_id | dump duplicate (USING + WITH CHECK) |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2858 | R | jarvis.current_user / jarvis.is_admin | dump duplicate |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2865 | R | jarvis.role / jarvis.current_user | dump duplicate |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2872 | R | jarvis.current_user / jarvis.role | dump duplicate |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2879 | R | jarvis.current_user / jarvis.role | dump duplicate |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2892 | R | app.profile_role | dump duplicate (×2) |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2905 | R | app.profile_role | dump duplicate (×2) |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2912 | R | app.profile_role | dump duplicate (×2) |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2925 | R | app.profile_role | dump duplicate (×2) |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2939 | R | rls.user_id | dump duplicate |
| db/postgres_schema.sql | 893 | R | jarvis.current_user / jarvis.role | `current_setting('jarvis.current_user'::text, true)` + `current_setting('jarvis.role'::text, true)` |
| db/postgres_schema.sql | 924 | R | jarvis.current_user | `current_setting('jarvis.current_user'::text, true)` |
| db/postgres_schema.sql | 931 | R | jarvis.current_user / jarvis.is_admin | `current_setting('jarvis.current_user'::text)` + `current_setting('jarvis.is_admin'::text, true)` |
| db/postgres_schema.sql | 940 | R | jarvis.current_user | `current_setting('jarvis.current_user'::text, true)` |
| db/postgres_schema.sql | 947 | R | jarvis.current_user | `current_setting('jarvis.current_user'::text, true)` |
| db/postgres_schema.sql | 956 | R | jarvis.current_user | `current_setting('jarvis.current_user'::text, true)` |
| gateway/dream/kill_switch.py | 60 | W | jarvis.role | `set_config('jarvis.role', 'platform_admin', true)` |
| scripts/smoke_5d1_watchdog_agent.sh | 61 | W | rls.user_id | `set_config('rls.user_id', 'system', true)` |

> Note: where multiple `current_setting()` calls appear on a single SQL line (common in dumped policies that combine `USING` + `WITH CHECK`), the row lists each namespace.name observed and ripgrep counts each call. Total row count above tracks distinct ripgrep hits (one per line); the headline counts above (84 jarvis reads, 58 app reads, 15 rls reads, 4 pgaudit reads = 161) are exact ripgrep hit totals.

---

## Section 3 — Per-file rollup

Sorted by total references DESC.

| file | reads_jarvis | writes_jarvis | reads_app | writes_app | reads_other | writes_other | total |
|---|---|---|---|---|---|---|---|
| db/baselines/baseline_2026-04-07_pre_step7.sql | 5 | 0 | 14 | 0 | 4 (rls) | 0 | 23 |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 5 | 0 | 14 | 0 | 4 (rls) | 0 | 23 |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 21 | 0 | 1 | 0 | 0 | 0 | 22 |
| brain/db/migrations/015_chat_rls_fix.sql | 0 | 0 | 8 | 0 | 4 (rls) | 0 | 12 |
| brain/db/migrations/009_child_profiles.sql | 0 | 0 | 12 | 0 | 0 | 0 | 12 |
| brain/db/migrations/20260414_180000_child_rls_policies.sql | 9 | 0 | 1 | 0 | 0 | 0 | 10 |
| brain/db/migrations/014_vault_rls_v1.sql | 0 | 0 | 8 | 0 | 0 | 0 | 8 |
| db/postgres_schema.sql | 6 | 0 | 0 | 0 | 0 | 0 | 6 |
| brain/db/rls.py | 0 | 2 | 0 | 3 | 0 | 0 | 5 |
| brain/db/migrations/20260422_160027_dream_rls_permissive_platform_admin.sql | 4 | 1 (SET LOCAL) | 0 | 0 | 0 | 0 | 5 |
| brain/db/migrations/006_task_graphs.sql | 4 | 0 | 0 | 0 | 0 | 0 | 4 |
| brain/db/migrations/20260417_120100_dream_cost_caps.sql | 4 | 0 | 0 | 0 | 0 | 0 | 4 |
| brain/db/migrations/20260416_080001_audit_stream_view.sql | 4 | 0 | 0 | 0 | 0 | 0 | 4 |
| brain/db/migrations/20260414_140000_approval_rls.sql | 4 | 0 | 0 | 0 | 0 | 0 | 4 |
| brain/db/migrations/20260429_170000_install_pgaudit.sql | 0 | 0 | 0 | 0 | 4 (pgaudit) | 0 | 4 |
| brain/routes/dev.py | 0 | 4 | 0 | 0 | 0 | 0 | 4 |
| brain/dream/_db.py | 0 | 2 | 0 | 0 | 0 | 0 | 2 |
| brain/services/dream_cost_cap_service.py | 0 | 2 | 0 | 0 | 0 | 0 | 2 |
| brain/services/dream_invariant_checker.py | 0 | 2 | 0 | 0 | 0 | 0 | 2 |
| brain/tasks/executor.py | 0 | 2 | 0 | 0 | 0 | 0 | 2 |
| db/alembic/versions/001_taskgraph.py | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| db/alembic/versions/003_chat_threads.py | 0 | 0 | 0 | 0 | 2 (rls) | 0 | 2 |
| brain/db/migrations/003_memory_tiers.sql | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| brain/db/migrations/20260414_160000_fix_semantic_isolation.sql | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| brain/db/migrations/20260417_120000_dream_invariants.sql | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| brain/db/migrations/20260417_130000_system_flags.sql | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| brain/db/migrations/20260417_131000_dream_model_policy.sql | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| brain/db/migrations/20260416_170000_cloud_costs_rls.sql | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| brain/db/migrations/20260414_150000_force_rls_stage6cd.sql | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| brain/db/migrations/008b_task_events.sql | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| brain/db/schema.sql | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| brain/db/migrations/012_watchdog_events.sql | 0 | 0 | 0 | 0 | 1 (rls) | 0 | 1 |
| brain/routes/dream_planning.py | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| brain/routes/internal_cost.py | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| gateway/dream/kill_switch.py | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| scripts/smoke_5d1_watchdog_agent.sh | 0 | 0 | 0 | 0 | 0 | 1 (rls) | 1 |
| brain/db/migrations/20260422_120001_alpha_cloud_costs_idempotency_key.sql | 0 | 1 (SET LOCAL) | 0 | 0 | 0 | 0 | 1 |
| brain/db/migrations/20260422_120002_alpha_system_flags_halt_severity.sql | 0 | 1 (SET LOCAL) | 0 | 0 | 0 | 0 | 1 |
| brain/db/migrations/20260422_120003_alpha_dream_sessions_status_halted.sql | 0 | 1 (SET LOCAL) | 0 | 0 | 0 | 0 | 1 |

**Sum check:** Reads_jarvis = 84, Writes_jarvis = 17 set_config + 4 SET LOCAL = 21, Reads_app = 58, Writes_app = 3, Reads_rls = 15, Writes_rls = 1, Reads_pgaudit = 4 ≡ 161 reads + 25 writes = 186 total references.

---

## Section 4 — SQL migrations cross-reference

Filtered to `.sql` files only. Excludes Python (`*.py`) and shell (`*.sh`). Includes migrations + dumps.

| file | line | type | namespace.name | full_call |
|---|---|---|---|---|
| brain/db/migrations/003_memory_tiers.sql | 36 | R | jarvis.current_user | `current_setting('jarvis.current_user')` |
| brain/db/migrations/003_memory_tiers.sql | 37 | R | jarvis.is_admin | `current_setting('jarvis.is_admin', true)` |
| brain/db/migrations/006_task_graphs.sql | 64,65,72,73 | R | jarvis.current_user / jarvis.role | as in Section 2 |
| brain/db/migrations/008b_task_events.sql | 35 | R | jarvis.current_user | `current_setting('jarvis.current_user', TRUE) = 'admin'` |
| brain/db/migrations/009_child_profiles.sql | 53–109 (12 hits) | R | app.profile_role / app.profile_id / app.max_rating | as in Section 2 |
| brain/db/migrations/012_watchdog_events.sql | 53 | R | rls.user_id | `current_setting('rls.user_id', true) = 'system'` |
| brain/db/migrations/014_vault_rls_v1.sql | 47–76 (8 hits) | R | app.profile_role | as in Section 2 |
| brain/db/migrations/015_chat_rls_fix.sql | 13–59 (12 hits) | R | rls.user_id (×4) / app.profile_role (×4) / app.profile_id (×4) | as in Section 2 |
| brain/db/migrations/20260414_130000_guc_canonicalize.sql | 107–214 (22 hits) | R | jarvis.role / jarvis.current_user / app.max_rating | as in Section 2 |
| brain/db/migrations/20260414_140000_approval_rls.sql | 18,19,24,25 | R | jarvis.role | as in Section 2 |
| brain/db/migrations/20260414_150000_force_rls_stage6cd.sql | 31,32 | R | jarvis.role | as in Section 2 |
| brain/db/migrations/20260414_160000_fix_semantic_isolation.sql | 12,13 | R | jarvis.current_user / jarvis.role | as in Section 2 |
| brain/db/migrations/20260414_180000_child_rls_policies.sql | 12–60 (10 hits) | R | jarvis.role (×7) / jarvis.current_user (×4) / app.max_rating (×1) | NB: regex hit count is 10 — line 39 has `jarvis.current_user` only |
| brain/db/migrations/20260416_080001_audit_stream_view.sql | 179,182,185,188 | R | jarvis.role | as in Section 2 |
| brain/db/migrations/20260416_170000_cloud_costs_rls.sql | 12,13 | R | jarvis.role | as in Section 2 |
| brain/db/migrations/20260417_120000_dream_invariants.sql | 36,37 | R | jarvis.role | as in Section 2 |
| brain/db/migrations/20260417_120100_dream_cost_caps.sql | 40,41,45,46 | R | jarvis.role | as in Section 2 |
| brain/db/migrations/20260417_130000_system_flags.sql | 21,22 | R | jarvis.role | as in Section 2 |
| brain/db/migrations/20260417_131000_dream_model_policy.sql | 38,39 | R | jarvis.role | as in Section 2 |
| brain/db/migrations/20260422_120001_alpha_cloud_costs_idempotency_key.sql | 3 | **W** | jarvis.role | `SET LOCAL jarvis.role = 'platform_admin';` |
| brain/db/migrations/20260422_120002_alpha_system_flags_halt_severity.sql | 3 | **W** | jarvis.role | `SET LOCAL jarvis.role = 'platform_admin';` |
| brain/db/migrations/20260422_120003_alpha_dream_sessions_status_halted.sql | 3 | **W** | jarvis.role | `SET LOCAL jarvis.role = 'platform_admin';` |
| brain/db/migrations/20260422_160027_dream_rls_permissive_platform_admin.sql | 3 | **W** | jarvis.role | `SET LOCAL jarvis.role = 'platform_admin';` |
| brain/db/migrations/20260422_160027_dream_rls_permissive_platform_admin.sql | 10,11,21,22 | R | jarvis.role | as in Section 2 |
| brain/db/migrations/20260429_170000_install_pgaudit.sql | 69,70,71,72 | R | pgaudit.* | `current_setting('pgaudit.log')`, `…log_relation`, `…log_parameter`, `…log_statement` |
| brain/db/schema.sql | 149 | R | jarvis.current_user | `current_setting('jarvis.current_user', true)` |
| db/postgres_schema.sql | 893,924,931,940,947,956 | R | jarvis.current_user / jarvis.role / jarvis.is_admin | dump artifact (6 line-hits, 9 distinct calls) |
| db/baselines/baseline_2026-04-07_pre_step7.sql | 2557–2765 (23 line-hits) | R | jarvis.* / app.* / rls.* | dump artifact |
| db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql | 2731–2939 (23 line-hits) | R | jarvis.* / app.* / rls.* | dump artifact (identical content to `pre_step7.sql`) |

**Migrations are the source of truth for the GUC contract.** Counting only files under `brain/db/migrations/` and the canonical `brain/db/schema.sql` + `db/alembic/versions/*.py` (migrations only):

| namespace | reads (migrations only) | writes (migrations only) |
|---|---|---|
| jarvis.* | 67 | 4 (SET LOCAL) |
| app.* | 30 | 0 |
| rls.* | 7 | 0 |
| pgaudit.* | 4 | 0 |

---

## Section 5 — Per-GUC rollup

Sorted by `total_reads + total_writes` DESC. Counts include dump artifacts and live code.

| guc_name (full) | total_reads | total_writes | files_touched | sample_call |
|---|---|---|---|---|
| `jarvis.role` | 47 | 16 | 21 | `current_setting('jarvis.role', true) = 'platform_admin'` |
| `jarvis.current_user` | 32 | 6 | 17 | `current_setting('jarvis.current_user', true)` |
| `app.profile_role` | 41 | 0 | 7 | `current_setting('app.profile_role', true) = 'admin'` |
| `rls.user_id` | 15 | 1 | 6 | `current_setting('rls.user_id', true) = 'system'` |
| `app.profile_id` | 8 | 0 | 4 | `current_setting('app.profile_id', true)` |
| `app.max_rating` | 6 | 1 | 6 | `current_setting('app.max_rating', true)` |
| `jarvis.is_admin` | 3 | 0 | 3 | `current_setting('jarvis.is_admin', true) = 'true'` (orphan — never written) |
| `pgaudit.log` | 1 | 0 | 1 | `current_setting('pgaudit.log')` |
| `pgaudit.log_relation` | 1 | 0 | 1 | `current_setting('pgaudit.log_relation')` |
| `pgaudit.log_parameter` | 1 | 0 | 1 | `current_setting('pgaudit.log_parameter')` |
| `pgaudit.log_statement` | 1 | 0 | 1 | `current_setting('pgaudit.log_statement')` |
| `app.user_id` | 0 | 1 | 1 | `set_config('app.user_id', $1, true)` (write-only — RLS policies do not read this) |
| `app.workspace_id` | 0 | 1 | 1 | `set_config('app.workspace_id', $1, true)` (write-only) |

**Read counts per GUC** are aggregated from the 161 ripgrep hits above. Lines with multiple distinct GUC names contribute to multiple rows. Verified totals: jarvis.role + jarvis.current_user + jarvis.is_admin = 47 + 32 + 3 = 82 distinct-call hits, slightly less than the 84 ripgrep line-hits because two `policy` lines combine two distinct jarvis.* calls onto a single line in dumps.

**Hot GUCs for migration:**
- `jarvis.role` — touched by 16 writes + 47 reads across 21 files; this is the highest-impact rename.
- `jarvis.current_user` — touched by 6 writes + 32 reads.
- `app.profile_role` — touched by 41 reads but **zero writes** in code under inventory: `app.profile_role` is read but never set by any `set_config` or `SET LOCAL`. (See Section 7 risk flag #4.)

---

## Section 6 — Unexpected namespaces

Namespaces that are **not** `jarvis.*` or `app.*`:

### `rls.*` (15 reads + 1 write)
This is the **target namespace** for Slab 2. It is already partially in use.

- **Readers (live code):**
  - `brain/db/migrations/012_watchdog_events.sql:53` — `current_setting('rls.user_id', true) = 'system'`
  - `brain/db/migrations/015_chat_rls_fix.sql` — lines 13, 14, 36, 42 (chat_threads + chat_messages isolation)
  - `db/alembic/versions/003_chat_threads.py` — lines 58, 65 (alembic version of the same policies)
  - Dumps: `db/baselines/baseline_2026-04-07_pre_step7.sql` (×4), `…with_grants.sql` (×4)
- **Writers:**
  - `scripts/smoke_5d1_watchdog_agent.sh:61` — `SET set_config('rls.user_id', 'system', true);` (the **only** writer of `rls.*` in the entire tree)

**Impact:** RLS policies on `chat_threads`, `chat_messages` (both via `015_chat_rls_fix.sql`), and `alpha_watchdog_events` (via `012_watchdog_events.sql`) currently depend on `rls.user_id`. The runtime writers (`brain/db/rls.py`, `brain/dream/_db.py`, etc.) **do not** set `rls.user_id` — they set `jarvis.current_user`. So today the only path that satisfies these policies is the smoke test script and the watchdog system role, plus any direct DB session. **This is broken / inconsistent and the Slab 2 migration must reconcile it** by either setting `rls.user_id` from `rls_connection()` going forward (preferred — aligns with the rls.* target namespace) or rewriting these three migrations to use `jarvis.current_user`.

### `pgaudit.*` (4 reads, 0 writes)
- `brain/db/migrations/20260429_170000_install_pgaudit.sql:69–72` — reads `pgaudit.log`, `pgaudit.log_relation`, `pgaudit.log_parameter`, `pgaudit.log_statement` to surface them in a `audit_pgaudit_config` view.

**Impact:** These are GUCs owned by the third-party pgaudit extension (Step 7 Slab 1 just installed it). They are **not** application GUCs and **must not** be migrated to `rls.*`. Treat them as out-of-scope for Slab 2.

### `pg_catalog.set_config('search_path', …)` — false positive
- `db/postgres_schema.sql:15`, `db/baselines/baseline_2026-04-07_pre_step7.sql:15`, `db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql:15`

These three calls use the built-in `search_path` GUC (no namespace dot in the variable name). They do not match the `[a-z_]+\.[a-z_]+` pattern for the variable itself (`'search_path'` has no dot) and are excluded from headline counts. They are `pg_dump` boilerplate.

---

## Section 7 — Migration risk flags

### Risk #1 — Dump artifacts will silently re-introduce old GUC names
- **Files:** `db/postgres_schema.sql`, `db/baselines/baseline_2026-04-07_pre_step7.sql`, `db/baselines/baseline_2026-04-07_pre_step7_with_grants.sql`
- **Issue:** These contribute 44 of the 161 reads. They are `pg_dump` outputs and reflect the **pre-migration** schema. Hand-editing them is wasteful (they'll be regenerated by the next baseline). But CI/tooling that diffs against these baselines will fail until they're regenerated.
- **Mitigation:** After Slab 2 lands, run `pg_dump` to refresh `db/postgres_schema.sql` and add a fresh `db/baselines/baseline_<date>_post_slab2.sql`. **Do not touch the pre-step7 baselines** — they are historical.

### Risk #2 — Inconsistent runtime: `rls.user_id` policy expects a value no Python writer sets
- **Affected policies:** `chat_threads_isolation`, `child_message_isolation` subqueries (in `015_chat_rls_fix.sql`), `watchdog_events_system_write` (in `012_watchdog_events.sql`)
- **Issue:** These three RLS policies read `rls.user_id`, but `brain/db/rls.py` only sets `jarvis.current_user` and `app.user_id`. Today, regular application requests that hit chat_threads/chat_messages succeed only because `child_thread_isolation` (a permissive policy) admits the request via a different predicate. If `child_thread_isolation` is ever tightened or removed, chat will silently break.
- **Mitigation:** Slab 2 must add `rls.user_id` to `rls_connection()` (or rename `rls.user_id` policies to read `jarvis.current_user`, depending on which name is canonical post-migration). Decide name before mechanical rewrite.

### Risk #3 — Orphan GUC: `jarvis.is_admin` (3 reads, 0 writes anywhere in tree)
- **Locations:** `brain/db/migrations/003_memory_tiers.sql:37`, `db/postgres_schema.sql:931`, `db/baselines/*.sql` (×2)
- **Issue:** `semantic_isolation` policy on `alpha_semantic_memory` has `OR current_setting('jarvis.is_admin', true) = 'true'` — but no code writes this GUC, so the admin escape hatch is permanently inoperative. Already documented in `docs/STEP6_5_PREFLIGHT.md:408` and `docs/STEP7_DISCOVERY.md:421`.
- **Mitigation:** Slab 2 should drop the `jarvis.is_admin` clause entirely (replace with `jarvis.role = 'platform_admin'` or the new `rls.role` equivalent). Do not just rename — delete the orphan branch.

### Risk #4 — Write-only orphans: `app.user_id`, `app.workspace_id`
- **Locations:** `brain/db/rls.py:92, 98`
- **Issue:** `rls_connection()` writes `app.user_id` and `app.workspace_id` on every request, but **no RLS policy or query in the codebase reads them**. They are dead writes.
- **Mitigation:** Slab 2 can drop these two `set_config` calls and skip naming them in the new namespace. (`app.max_rating` IS read by `child_content_rating` and `child_memory_rating` policies, so keep it.)

### Risk #5 — Hot path: GUCs are set per-request inside transactions
- **Affected files (all are hot paths):**
  - `brain/db/rls.py` — FastAPI request hook (every request)
  - `brain/dream/_db.py` — Temporal activity entry (every dream-step activity)
  - `brain/services/dream_invariant_checker.py:145, 306` — invariant check loop
  - `brain/services/dream_cost_cap_service.py:46, 128` — cost cap check loop
  - `brain/routes/dev.py:55, 59, 274, 278` — dev sandbox routes
  - `brain/routes/dream_planning.py:76`, `brain/routes/internal_cost.py:97`, `gateway/dream/kill_switch.py:60` — service entry points
  - `brain/tasks/executor.py:46, 48` — task executor entry
- **Issue:** `set_config(..., …, true)` is transaction-scoped. The migration must preserve transaction semantics: any rename is safe so long as the new name is set inside the same transaction as the queries that read it. **All current writers do this correctly**. The risk is if a refactor moves the write outside the transaction (e.g., into a connection pool initializer using `false` instead of `true`).
- **Mitigation:** Slab 2 should preserve the `true` (transaction-local) flag on every rewritten `set_config` call. Add a CI check that lints for `set_config('rls.…', …, false)` post-migration.

### Risk #6 — No dynamic GUC names — mechanical rewrite is safe
- **Verified:** Every `current_setting()` and `set_config()` call in the tree uses a literal-string GUC name. There are no f-strings, no string concatenation, no parameterized GUC names. Mechanical sed-style rewrite is feasible.

### Risk #7 — `SET LOCAL` writes are easy to miss in regex-based linting
- **Affected migrations:**
  - `brain/db/migrations/20260422_120001_alpha_cloud_costs_idempotency_key.sql:3`
  - `brain/db/migrations/20260422_120002_alpha_system_flags_halt_severity.sql:3`
  - `brain/db/migrations/20260422_120003_alpha_dream_sessions_status_halted.sql:3`
  - `brain/db/migrations/20260422_160027_dream_rls_permissive_platform_admin.sql:3`
- **Issue:** The original memory regex (`set_config\(...)`) missed these. Any pre-merge audit must search for both `set_config\(\s*['"]` AND `^\s*SET\s+(LOCAL\s+)?[a-z_]+\.[a-z_]+`.
- **Mitigation:** Add both patterns to the Slab 2 verification script.

### Risk #8 — Migration ordering: `20260414_130000_guc_canonicalize.sql` was an earlier attempt
- **File:** `brain/db/migrations/20260414_130000_guc_canonicalize.sql` — 22 GUC references, the highest of any single file.
- **Note:** Its name suggests prior canonicalization work. Slab 2 will be re-canonicalizing the canonicalization. Make sure the new migration drops/replaces policies created here cleanly (a fresh `DROP POLICY IF EXISTS … CREATE POLICY …` per affected table is safer than `CREATE OR REPLACE`).

---

## Appendix — Verification commands

To reproduce the headline counts:

```bash
# jarvis.* reads (84)
rg -c "current_setting\(\s*['\"]jarvis\." . --glob '*.py' --glob '*.sql' --glob '*.psql' --glob '*.sh' \
  | awk -F: '{s+=$2} END {print s}'

# jarvis.* set_config writes (17)
rg -c "set_config\(\s*['\"]jarvis\." . --glob '*.py' --glob '*.sql' --glob '*.psql' --glob '*.sh' \
  | awk -F: '{s+=$2} END {print s}'

# jarvis.* SET LOCAL writes (4)
rg -i "^\s*SET\s+(LOCAL\s+)?jarvis\." . --glob '*.sql' --glob '*.psql' --glob '*.sh' | wc -l

# app.* reads (58)
rg -c "current_setting\(\s*['\"]app\." . --glob '*.py' --glob '*.sql' --glob '*.psql' --glob '*.sh' \
  | awk -F: '{s+=$2} END {print s}'

# rls.* reads (15)
rg -c "current_setting\(\s*['\"]rls\." . --glob '*.py' --glob '*.sql' --glob '*.psql' --glob '*.sh' \
  | awk -F: '{s+=$2} END {print s}'

# pgaudit.* reads (4)
rg -c "current_setting\(\s*['\"]pgaudit\." . --glob '*.py' --glob '*.sql' --glob '*.psql' --glob '*.sh' \
  | awk -F: '{s+=$2} END {print s}'

# Python files writing jarvis.* (9)
rg -l "set_config\(\s*['\"]jarvis\." . --glob '*.py' | wc -l
```
