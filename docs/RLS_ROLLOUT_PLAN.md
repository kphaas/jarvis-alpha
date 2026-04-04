# RLS Rollout Plan — jarvis-alpha

Design Spec · April 2026 · Status: REVIEWED (Perplexity pass incorporated)

---

## 1. Summary

Row-Level Security (RLS) ensures the database enforces data isolation — not the application. Today only `alpha_conversation_memory` has RLS. This plan extends RLS to every profile-scoped table and adds DB-layer child safety enforcement.

**Core rule:** If a query runs as a child profile, the database itself prevents access to unauthorized data — regardless of what the application code does.

---

## 2. Current State

| Table | Has RLS | Policy Name | Notes |
|---|---|---|---|
| alpha_conversation_memory | ✅ YES | alpha_memory_isolation | Only table protected today |
| All other tables | ❌ NO | — | App-layer filtering only |

### What RLS Middleware Already Does

`RLSContextMiddleware` (runs after Auth) sets Postgres session variables per request:

```sql
SET app.current_user = 'ken';
SET app.current_role = 'admin';
```

These variables are available to RLS policies via `current_setting()`.

**Gaps to fix:**
- Middleware does not set `app.actor_type` or `app.profile_type`
- Middleware does not set `app.current_role` for services/agents
- Middleware does not set sentinel values for unauthenticated requests
- Middleware re-decodes JWT instead of reading from `request.state` (set by Auth)

---

## 3. Design Principles

1. **RLS is mandatory for any table that stores per-user or per-profile data.**
2. **Admin bypass is explicit.** Admin role can see all rows via a named policy, not absence of policy.
3. **Child profiles are restricted at the DB layer.** Even if app code has a bug, children cannot see adult data.
4. **Services see only what their scopes allow.** Forge reads pipeline data. Gateway cannot read memory.
5. **One Postgres role (`jarvis_alpha_app`) with session variables.** No separate DB roles per profile — all access control via RLS policies checking session vars.
6. **Policies OR, not AND.** Multiple policies on the same table/operation are combined with OR. This is intentional — admin sees all rows via `admin_full_access`, users see own rows via `user_own_rows`, and both policies returning true is correct behavior.
7. **All `current_setting()` calls use the `true` fallback arg.** Missing var returns NULL → policies evaluate to false (deny) — never throws an error.

---

## 4. Session Variables — Extended

RLS middleware sets these on every request. **RLS middleware reads from `request.state` (set by Auth middleware) — it never re-decodes the JWT.**

| Variable | Source | Example Values |
|---|---|---|
| `app.current_user` | JWT `sub` | ken, ryleigh, sloane, forge, buddy |
| `app.actor_type` | JWT `actor_type` | user, service, agent |
| `app.current_role` | JWT `role` or derived (see below) | admin, adult, child, service, agent |
| `app.profile_type` | Derived from role | adult, child, service, agent |

### Derivation Rules

| actor_type | JWT role | → current_role | → profile_type |
|---|---|---|---|
| `user` | `admin` | `admin` | `adult` |
| `user` | `adult` | `adult` | `adult` |
| `user` | `child` | `child` | `child` |
| `service` | (none) | `service` | `service` |
| `agent` | (none) | `agent` | `agent` |

### Unauthenticated / Failed Auth Requests

If Auth fails or request reaches DB without session vars, middleware MUST set all 4 vars to sentinel values:

```sql
SET app.current_user = '_none';
SET app.actor_type = '_none';
SET app.current_role = '_none';
SET app.profile_type = '_none';
```

No policy matches `'_none'` → 0 rows returned. This is denial by evaluation, not by error.

---

## 5. Table Classification

### 5.1 User-Scoped Tables (per-user RLS)

| Table | Owner Column | Exists Today? | Child Access |
|---|---|---|---|
| alpha_conversation_memory | `user_id` | ✅ has RLS | Own rows only |
| chat_threads | `user_id` | ⚠️ needs column check | Own threads only |
| chat_messages | via `thread_id` FK | Inherits from thread | Own messages only |
| thread_memory_extracts | `user_id` | ⚠️ needs column check | Own extracts only |
| alpha_task_graphs | `created_by` | ⚠️ needs column check | **No access** |
| alpha_task_steps | via `graph_id` FK | Inherits from graph | **No access** |

### 5.2 Project-Scoped Tables

| Table | Scope Column | Child Access |
|---|---|---|
| alpha_projects | `owner_id` or membership | **No access** to `forge` or `problem` types |

### 5.3 Approval Tables (depend on Doc 2 schema — must exist first)

| Table | Who Can Read | Who Can Write |
|---|---|---|
| alpha_approval_queue | Admin (all), adults (all pending), requesting actor (own) | System insert, admin update status |
| alpha_approval_audit | Admin only | System insert only (no update/delete — REVOKE enforced) |
| alpha_overnight_approvals | Admin only | Admin only |

### 5.4 System Tables (RLS, not GRANT/REVOKE)

Since all profiles run as one DB role (`jarvis_alpha_app`), GRANT/REVOKE per profile type doesn't work. All tables use RLS with session variables.

| Table | Who Can Read | Who Can Write |
|---|---|---|
| alpha_node_registry | Admin, adults, services, agents | Admin, services |
| alpha_buddy_events | Admin, adults, agents | Buddy agent only |

### 5.5 Forge Tables on Brain Postgres

| Table | Who Can Read | Who Can Write |
|---|---|---|
| pipeline_lessons | Admin, forge service | Forge service |
| pipeline_trust_scores | Admin, forge service | Forge service |
| pipeline_metrics_brain | Admin, forge service | Forge service |

---

## 6. Policy Definitions

**Rule:** All `current_setting()` calls use `current_setting('var', true)` — returns NULL if unset, policies evaluate to false (deny).

### 6.1 Pattern: User-Owned Data

Applied to: `chat_threads`, `thread_memory_extracts`

```sql
ALTER TABLE chat_threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_threads FORCE ROW LEVEL SECURITY;

-- Admin sees all
CREATE POLICY admin_full_access ON chat_threads
    FOR ALL
    USING (current_setting('app.current_role', true) = 'admin');

-- Users (adult + child) see own rows
CREATE POLICY user_own_rows ON chat_threads
    FOR ALL
    USING (user_id = current_setting('app.current_user', true))
    WITH CHECK (user_id = current_setting('app.current_user', true));
```

### 6.2 Pattern: FK-Inherited Access

Applied to: `chat_messages` (inherits from `chat_threads`), `alpha_task_steps` (inherits from `alpha_task_graphs`)

```sql
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages FORCE ROW LEVEL SECURITY;

-- Admin sees all
CREATE POLICY admin_full_access ON chat_messages
    FOR ALL
    USING (current_setting('app.current_role', true) = 'admin');

-- Users see messages in their own threads
CREATE POLICY user_own_messages ON chat_messages
    FOR ALL
    USING (
        thread_id IN (
            SELECT id FROM chat_threads
            WHERE user_id = current_setting('app.current_user', true)
        )
    )
    WITH CHECK (
        thread_id IN (
            SELECT id FROM chat_threads
            WHERE user_id = current_setting('app.current_user', true)
        )
    );
```

**⚠️ FK subquery runs under RLS.** The subquery on `chat_threads` is also subject to RLS policies. This is correct — a user can only see messages in threads they own. **Test this explicitly** — FK subquery RLS inheritance is a common silent failure point.

### 6.3 Pattern: Child Blocked + Service Scoped

Applied to: `alpha_task_graphs`

```sql
ALTER TABLE alpha_task_graphs ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_task_graphs FORCE ROW LEVEL SECURITY;

-- Admin sees all
CREATE POLICY admin_full_access ON alpha_task_graphs
    FOR ALL
    USING (current_setting('app.current_role', true) = 'admin');

-- Adults see own graphs
CREATE POLICY adult_own_graphs ON alpha_task_graphs
    FOR ALL
    USING (
        current_setting('app.profile_type', true) = 'adult'
        AND created_by = current_setting('app.current_user', true)
    )
    WITH CHECK (
        current_setting('app.profile_type', true) = 'adult'
        AND created_by = current_setting('app.current_user', true)
    );

-- Children: no policy = 0 rows

-- Services see graphs they created
CREATE POLICY service_own_graphs ON alpha_task_graphs
    FOR ALL
    USING (
        current_setting('app.actor_type', true) = 'service'
        AND created_by = current_setting('app.current_user', true)
    );

-- Buddy agent: read only (for stuck task scanning)
CREATE POLICY agent_read_graphs ON alpha_task_graphs
    FOR SELECT
    USING (current_setting('app.actor_type', true) = 'agent');
```

### 6.4 Pattern: Service-Scoped

Applied to: `pipeline_lessons`, `pipeline_trust_scores`, `pipeline_metrics_brain`

```sql
ALTER TABLE pipeline_lessons ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_lessons FORCE ROW LEVEL SECURITY;

-- Admin sees all
CREATE POLICY admin_full_access ON pipeline_lessons
    FOR ALL
    USING (current_setting('app.current_role', true) = 'admin');

-- Forge service sees its own data
CREATE POLICY forge_own_data ON pipeline_lessons
    FOR ALL
    USING (
        current_setting('app.current_user', true) = 'forge'
        AND current_setting('app.actor_type', true) = 'service'
    );
```

### 6.5 Pattern: Approval Queue

```sql
ALTER TABLE alpha_approval_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_approval_queue FORCE ROW LEVEL SECURITY;

-- Admin sees all
CREATE POLICY admin_full_access ON alpha_approval_queue
    FOR ALL
    USING (current_setting('app.current_role', true) = 'admin');

-- Adult approvers see ALL pending approvals (not just their own)
CREATE POLICY adult_pending_approvals ON alpha_approval_queue
    FOR SELECT
    USING (
        current_setting('app.profile_type', true) = 'adult'
        AND status = 'pending'
    );

-- Requesting actor sees own requests (any status)
CREATE POLICY actor_own_requests ON alpha_approval_queue
    FOR SELECT
    USING (actor_sub = current_setting('app.current_user', true));

-- Children: no policy = 0 rows
```

### 6.6 Pattern: Immutable Audit

Applied to: `alpha_approval_audit`

```sql
ALTER TABLE alpha_approval_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_approval_audit FORCE ROW LEVEL SECURITY;

-- Admin can read all
CREATE POLICY admin_read ON alpha_approval_audit
    FOR SELECT
    USING (current_setting('app.current_role', true) = 'admin');

-- System can insert (any authenticated actor)
CREATE POLICY system_insert ON alpha_approval_audit
    FOR INSERT
    WITH CHECK (true);

-- No UPDATE or DELETE policies = no modification possible
-- Belt + suspenders: REVOKE also applied (Doc 2)
```

### 6.7 Pattern: System Tables (via RLS, not GRANT)

Applied to: `alpha_buddy_events`, `alpha_node_registry`

```sql
ALTER TABLE alpha_buddy_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_buddy_events FORCE ROW LEVEL SECURITY;

-- Admin sees all
CREATE POLICY admin_full_access ON alpha_buddy_events
    FOR ALL
    USING (current_setting('app.current_role', true) = 'admin');

-- Adults can read
CREATE POLICY adult_read ON alpha_buddy_events
    FOR SELECT
    USING (current_setting('app.profile_type', true) = 'adult');

-- Buddy agent can read and write
CREATE POLICY agent_write ON alpha_buddy_events
    FOR ALL
    USING (current_setting('app.current_user', true) = 'buddy')
    WITH CHECK (current_setting('app.current_user', true) = 'buddy');

-- Children: no policy = 0 rows
-- Other services: no policy = 0 rows
```

---

## 7. Child Safety — DB Layer Enforcement

### 7.1 What Children Cannot See (enforced by absence of policy)

| Data | Enforcement |
|---|---|
| Other users' memory | RLS user_own_rows policy |
| Other users' threads | RLS user_own_rows policy |
| Task graphs / steps | No child policy = 0 rows |
| Approval queue / audit | No child policy = 0 rows |
| Overnight approvals | No child policy = 0 rows |
| Pipeline lessons / metrics | No child policy = 0 rows |
| Cost data | No child policy on costs tables |
| Buddy events | No child policy = 0 rows |
| Node registry | No child policy = 0 rows |

### 7.2 What Children CAN See (explicit policies)

| Data | Policy | Restrictions |
|---|---|---|
| Own conversation memory | `user_own_rows` on alpha_conversation_memory | Own rows only |
| Own chat threads | `user_own_rows` on chat_threads | Max 5 threads (trigger enforced) |
| Own chat messages | `user_own_messages` on chat_messages | Inherited from thread ownership |
| Home summary | Route-level filtering | Filtered view — no costs, no security |

### 7.3 Child Thread Limit Trigger

```sql
CREATE OR REPLACE FUNCTION enforce_child_thread_limit()
RETURNS TRIGGER AS $$
BEGIN
    IF current_setting('app.profile_type', true) = 'child' THEN
        IF (SELECT count(*) FROM chat_threads
            WHERE user_id = NEW.user_id) >= 5 THEN
            RAISE EXCEPTION 'Child profile thread limit reached (max 5)';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER child_thread_limit
    BEFORE INSERT ON chat_threads
    FOR EACH ROW EXECUTE FUNCTION enforce_child_thread_limit();
```

**Note:** Race condition under concurrent inserts. Accepted for household system — children won't be inserting threads concurrently.

---

## 8. Buddy Agent Access

Buddy runs as `actor_type=agent`, `current_role=agent` on Brain. It needs specific access:

| Table | Access | Policy |
|---|---|---|
| alpha_conversation_memory | **SELECT + UPDATE only** (eviction/promotion) | See below |
| alpha_buddy_events | Read + write | agent_write policy (Section 6.7) |
| alpha_task_graphs | Read only (stuck scan) | agent_read_graphs (Section 6.3) |

### Buddy Memory Policy — SELECT + UPDATE Only

```sql
-- Buddy can read all memory (cross-user, needed for eviction/promotion)
CREATE POLICY agent_memory_read ON alpha_conversation_memory
    FOR SELECT
    USING (current_setting('app.actor_type', true) = 'agent');

-- Buddy can update memory_type and updated_at (eviction/promotion)
CREATE POLICY agent_memory_update ON alpha_conversation_memory
    FOR UPDATE
    USING (current_setting('app.actor_type', true) = 'agent')
    WITH CHECK (current_setting('app.actor_type', true) = 'agent');

-- No INSERT policy for agent = Buddy cannot create new memory rows
-- No DELETE policy for agent = Buddy cannot hard-delete rows
```

**Risk acknowledged:** Buddy can read ALL memory (cross-user) because eviction/promotion requires scanning all rows. This is acceptable because Buddy runs on Brain with a narrow-scoped token. The UPDATE-only restriction prevents Buddy from creating unauthorized memory.

---

## 9. Migration Plan

### Dependencies

**⚠️ Approval tables (`alpha_approval_queue`, `alpha_approval_audit`, `alpha_overnight_approvals`) must exist before Phase D.** These are created in the Approval Gateway migration (Doc 2, Step 1). Sequence: Doc 1 → Doc 2 tables → Doc 3 Phase D.

### Phase A — Middleware Update (prerequisite)

| Step | What | Effort |
|---|---|---|
| A1 | RLS middleware reads from `request.state` (set by Auth), not re-decodes JWT | 15 min |
| A2 | Add `app.actor_type` to SET statements | 10 min |
| A3 | Add `app.current_role` — use derivation table (admin/adult/child/service/agent) | 15 min |
| A4 | Add `app.profile_type` derivation logic | 10 min |
| A5 | Set all 4 vars to `'_none'` sentinel for unauthenticated/failed-auth requests | 10 min |
| A6 | Test: verify all 4 vars set correctly per actor type (user, service, agent, unauth) | 15 min |

### Phase B — User-Scoped Tables

| Step | What | Effort |
|---|---|---|
| B1 | Verify `user_id` / `created_by` columns exist on all target tables | 15 min |
| B2 | Add missing owner columns. **Backfill carefully:** use actual creator where knowable, `'_unknown'` for ambiguous rows. Never blindly backfill 'ken' on Forge-created data. | 30 min |
| B3 | Enable RLS + create policies on `chat_threads` | 15 min |
| B4 | Enable RLS + create policies on `chat_messages` (FK pattern) | 15 min |
| B5 | Enable RLS + create policies on `thread_memory_extracts` | 15 min |
| B6 | Enable RLS + create policies on `alpha_task_graphs` | 15 min |
| B7 | Enable RLS + create policies on `alpha_task_steps` (FK pattern) | 15 min |
| B8 | Enable RLS + create policies on `alpha_projects` | 15 min |

### Phase C — Child Safety

| Step | What | Effort |
|---|---|---|
| C1 | Create child-specific policies (own memory, own threads) | 20 min |
| C2 | Create child thread limit trigger | 10 min |
| C3 | Verify: no child policy exists on admin/cost/security/pipeline tables | 15 min |
| C4 | Test: child profile query → 0 rows on task_graphs, approval, costs, buddy_events | 20 min |
| C5 | Test: child profile query → own memory/threads only | 15 min |

### Phase D — Service + Agent Policies (requires approval tables from Doc 2)

| Step | What | Effort |
|---|---|---|
| D1 | Create Forge service policies on pipeline_* tables | 15 min |
| D2 | Create Buddy agent policies — SELECT + UPDATE on memory, read-only on graphs | 15 min |
| D3 | Enable RLS on approval tables (must already exist from Doc 2 migration) | 15 min |
| D4 | Create approval queue policies (admin all, adult pending, actor own) | 15 min |
| D5 | Enable RLS on system tables (buddy_events, node_registry) | 15 min |
| D6 | Test: Forge token → can write lessons, cannot read memory | 15 min |
| D7 | Test: Buddy token → can SELECT + UPDATE memory, cannot INSERT | 15 min |
| D8 | Test: FK subquery — Forge reads task_steps via task_graphs RLS | 15 min |

### Phase E — Validation

| Step | What | Effort |
|---|---|---|
| E1 | SQL test: admin sees all rows on every RLS-protected table | 15 min |
| E2 | SQL test: child sees only own data, 0 rows on admin/cost/security tables | 15 min |
| E3 | SQL test: forge sees only pipeline data, 0 rows on memory/threads | 15 min |
| E4 | SQL test: `'_none'` sentinel (unauthenticated) sees 0 rows everywhere | 15 min |
| E5 | SQL test: adult approver sees ALL pending approvals (not just own) | 10 min |
| E6 | SQL test: buddy can UPDATE memory but NOT INSERT or DELETE | 10 min |
| E7 | Document all policies in a single reference table | 20 min |

### Effort Summary

| Phase | Effort |
|---|---|
| A — Middleware | ~1.25 hours |
| B — User-scoped | ~2.25 hours |
| C — Child safety | ~1.5 hours |
| D — Service/agent + approval | ~2 hours |
| E — Validation | ~1.5 hours |
| **Total** | **~8.5 hours** |

---

## 10. Rollback Plan

If RLS breaks a running service:

1. **Immediate:** `ALTER TABLE <table> DISABLE ROW LEVEL SECURITY;` — one command, instant rollback per table
2. **Diagnostic:** Check `app.current_user` is being set — most failures are missing session variable
3. **Safe order:** Enable RLS one table at a time, test, then move to next
4. **⚠️ Window risk:** Disabling RLS exposes ALL rows to ALL authenticated users until re-enabled. Acceptable for emergency rollback, not for extended periods.

**Critical:** Create policies BEFORE enabling RLS on a table. Enabling RLS with no policies = 0 rows for non-superuser.

---

## 11. What This Does NOT Cover

- **Column-level security** — RLS controls row access, not which columns a child sees within allowed rows. Content filtering (e.g., hiding cost fields from home summary) stays at the application/route layer.
- **Child content filtering on AI responses** — Brain must filter LLM output before returning to child profiles. This is app-layer middleware (Doc 1, Section 8.3), not a DB concern.
- **Cross-database RLS** — Forge SQLite on Sandbox has no RLS. Forge is single-user (service identity), so not needed.
- **alpha_workspaces** — deferred until multi-user workspace feature is built. When built, inherits `alpha_projects` RLS pattern.

---

## 12. Policy Reference Table

All tables use RLS with session variables. No GRANT/REVOKE per profile (single `jarvis_alpha_app` DB role).

| Table | RLS | Admin | Adult | Child | Forge | Buddy |
|---|---|---|---|---|---|---|
| alpha_conversation_memory | ✅ | All | Own | Own | ❌ | SELECT + UPDATE all |
| chat_threads | NEW | All | Own | Own (max 5) | ❌ | ❌ |
| chat_messages | NEW | All | Own threads | Own threads | ❌ | ❌ |
| thread_memory_extracts | NEW | All | Own | Own | ❌ | ❌ |
| alpha_task_graphs | NEW | All | Own | ❌ | Own | SELECT only |
| alpha_task_steps | NEW | All | Own graphs | ❌ | Own graphs | SELECT only |
| alpha_projects | NEW | All | Own | Limited | ❌ | ❌ |
| alpha_approval_queue | NEW | All | All pending | ❌ | Own requests | ❌ |
| alpha_approval_audit | NEW | SELECT | ❌ | ❌ | ❌ | ❌ |
| alpha_overnight_approvals | NEW | All | ❌ | ❌ | ❌ | ❌ |
| pipeline_lessons | NEW | All | ❌ | ❌ | Own | ❌ |
| pipeline_trust_scores | NEW | All | ❌ | ❌ | Own | ❌ |
| pipeline_metrics_brain | NEW | All | ❌ | ❌ | Own | ❌ |
| alpha_node_registry | NEW | All | Read | ❌ | Read | Read |
| alpha_buddy_events | NEW | All | Read | ❌ | ❌ | Read + Write |

---

## 13. Cross-Spec Middleware Integration

All three specs interact at the middleware layer:

```
CORS → Auth (JWT + iss/actor_type) → Scopes → RLS (session vars) → RateLimit → handler
```

**RLS middleware is a consumer of Auth middleware:**
1. Auth middleware validates JWT, attaches decoded claims to `request.state`
2. RLS middleware reads `request.state.claims` — never re-decodes the token
3. RLS middleware SETs all 4 Postgres session vars from the Auth output
4. If Auth failed → RLS middleware SETs all vars to `'_none'` sentinel

---

*RLS Rollout Plan V2 · jarvis-alpha · April 2026 · Perplexity review incorporated*
