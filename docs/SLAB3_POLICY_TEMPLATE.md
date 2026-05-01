# SLAB 3 — RLS Policy Template (Canonical)

**Locked:** May 1, 2026
**Supersedes:** Apr 27 PATTERNS.md draft (sentinel section)
**Referenced by:** Slab 4 (SECDEF fleet), Slab 5 (bug fixes), Slab 6 (atomic policy deploy)

## Locked decisions

- **Q4 (A):** Two security models — user-scoped (Shape A) and admin-only (Shape B). Shape A has two access variants: direct (`A`) and FK-inherited (`A-FK`).
- **Q5 (B):** RESTRICTIVE child overlay only on tables children directly read or write.
- **Q6 (C):** Defense-in-depth — CI check at PR + DB event trigger at runtime.
- **Q7 (B):** Extend `brain/db/tests/rls_smoke.sql` with role-switching cases.
- **System sentinel (D):** No sentinel UUID. Shape B tables keep `user_id` NULLABLE. System writes go through SECURITY DEFINER (Slab 4).

## GUC namespace (locked Slab 2)

| Name | Type | Source |
|---|---|---|
| rls.user_id | UUID (cast at use) | JWT sub claim |
| rls.role | TEXT — platform_admin / user / child | JWT role claim |
| rls.max_rating | TEXT — all_ages / age_8_plus / teen / adult | child profile |
| rls.workspace_id | UUID (cast at use) | JWT workspace claim |

All policies use `current_setting('<name>', true)` — returns NULL if unset, policies evaluate to false (fail-closed).

---

## Shape A — User-scoped (direct)

Use for: tables with own `user_id` column.

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;

CREATE POLICY <table>_user_or_admin ON <table>
  AS PERMISSIVE
  FOR ALL
  USING (
    current_setting('rls.role', true) = 'platform_admin'
    OR user_id = current_setting('rls.user_id', true)::uuid
  )
  WITH CHECK (
    current_setting('rls.role', true) = 'platform_admin'
    OR user_id = current_setting('rls.user_id', true)::uuid
  );

ALTER TABLE <table> FORCE ROW LEVEL SECURITY;
```

### Notes
- USING ≡ WITH CHECK by design — every visible row must be valid for INSERT/UPDATE
- `::uuid` cast on unset/empty GUC fails → policy returns false → fail-closed
- Shape A tables hold ONLY user rows (per Q4-A). No system rows mixed in.

---

## Shape A-FK — User-scoped (FK-inherited)

Use for: tables that inherit user identity via FK to a Shape A parent.

Example: `chat_messages.thread_id` → `chat_threads.id` → `chat_threads.user_id`.

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;

CREATE POLICY <table>_user_or_admin ON <table>
  AS PERMISSIVE
  FOR ALL
  USING (
    current_setting('rls.role', true) = 'platform_admin'
    OR EXISTS (
      SELECT 1 FROM <parent_table> p
      WHERE p.id = <table>.<parent_fk_column>
        AND p.user_id = current_setting('rls.user_id', true)::uuid
    )
  )
  WITH CHECK (
    current_setting('rls.role', true) = 'platform_admin'
    OR EXISTS (
      SELECT 1 FROM <parent_table> p
      WHERE p.id = <table>.<parent_fk_column>
        AND p.user_id = current_setting('rls.user_id', true)::uuid
    )
  );

ALTER TABLE <table> FORCE ROW LEVEL SECURITY;
```

### FK-inheritance gotcha
- The EXISTS subquery on `<parent_table>` is also subject to RLS. Correct security behavior, but creates a perf consideration.
- Mandatory composite index: `<parent_table>(id, user_id)` covers the EXISTS check.
- Test FK-inheritance explicitly in Slab 5 smoke harness — common silent failure point.

---

## Shape B — Admin-only

Use for: tables holding system / agent / audit data.

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;

CREATE POLICY <table>_admin_only ON <table>
  AS PERMISSIVE
  FOR ALL
  USING (current_setting('rls.role', true) = 'platform_admin')
  WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

ALTER TABLE <table> FORCE ROW LEVEL SECURITY;
```

### Notes
- Policy does NOT reference `user_id`. NULLable user_id is fine (decision D).
- Background agents write via SECURITY DEFINER (Slab 4) — function sets `rls.role='platform_admin'` for execution context.
- "System actor" is application-level convention, NOT a DB-enforced sentinel.

---

## RESTRICTIVE child overlay

Layered ON TOP of Shape A or Shape A-FK for tables children directly read or write.

### On Shape A (rating column on the table itself)

```sql
CREATE POLICY <table>_child_rating_ceiling ON <table>
  AS RESTRICTIVE
  FOR SELECT
  USING (
    current_setting('rls.role', true) <> 'child'
    OR rating_ceiling_check(content_rating, current_setting('rls.max_rating', true))
  );
```

### On Shape A-FK (rating column on the parent)

```sql
CREATE POLICY <table>_child_rating_ceiling ON <table>
  AS RESTRICTIVE
  FOR SELECT
  USING (
    current_setting('rls.role', true) <> 'child'
    OR EXISTS (
      SELECT 1 FROM <parent_table> p
      WHERE p.id = <table>.<parent_fk_column>
        AND rating_ceiling_check(p.content_rating, current_setting('rls.max_rating', true))
    )
  );
```

`rating_ceiling_check()` is a SECURITY DEFINER helper — defined in Slab 4.

---

## Production inventory (May 1, 2026)

22 RLS-enabled tables. Every one has at least one PERMISSIVE policy (Q6 invariant holds).

| Table | Current shape | Slab 6 verify |
|---|---|---|
| chat_threads | A + child overlay | OK — canonical match |
| alpha_conversation_memory | A + child overlay | OK — canonical match |
| chat_messages | A-FK (via chat_threads) + child overlay | VERIFY EXISTS body matches A-FK template |
| alpha_task_graphs | A | VERIFY — has child_profile_scope RESTRICTIVE; admin/service path, why child overlay? |
| alpha_task_steps | A (or A-FK from alpha_task_graphs) | VERIFY if user_id is denormalized or canonical |
| alpha_semantic_memory | A | OK — canonical match |
| alpha_buddy_events | A (has user_id) | VERIFY intent — agent events suggest Shape B with NULLable user_id |
| vault_access_log | A (has user_id) | VERIFY intent — access logs typically Shape B |
| alpha_approval_audit | B | OK — canonical match |
| alpha_approval_queue | B | OK — canonical match |
| alpha_cloud_costs | B | VERIFY — FORCE RLS off; Slab 6 enables FORCE |
| alpha_dream_blocked_writes | B | OK — canonical match |
| alpha_dream_cost_caps | B | OK — canonical match |
| alpha_dream_cost_counters | B | OK — canonical match |
| alpha_dream_model_policy | B | OK — canonical match |
| alpha_dream_sessions | B | VERIFY — has child_profile_scope RESTRICTIVE; Dream sessions are admin/service |
| alpha_dream_steps | B | OK — canonical match |
| alpha_system_flags | B | OK — canonical match |
| alpha_task_events | B | VERIFY — Apr 27 Lock 8 bug (literal 'admin') — Slab 5 fixes |
| alpha_watchdog_events | B | VERIFY — 2 PERMISSIVE policies (read + system_write); consolidate? |
| vault_documents | B | VERIFY — 2 PERMISSIVE policies (read + write); consolidate? |
| vault_pipeline | B | OK — canonical match |

---

## Structural invariant (Q6-C)

Every RLS-enabled table MUST have at least one PERMISSIVE policy. Without it, all queries return zero rows — silent fail-closed. Production already satisfies this; layers below block future regressions.

### Layer 1 — CI check at PR time (Slab 4)

```python
def test_every_rls_table_has_permissive_policy():
    rls_tables = query("""
        SELECT relname FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND (c.relrowsecurity = true OR c.relforcerowsecurity = true)
    """)
    for t in rls_tables:
        n = query("""
            SELECT count(*) FROM pg_policies
            WHERE schemaname='public' AND tablename=%s AND permissive='PERMISSIVE'
        """, [t])
        assert n >= 1, f"Table {t} has RLS enabled but no PERMISSIVE policy"
```

### Layer 2 — DB event trigger (Slab 4)

```sql
CREATE OR REPLACE FUNCTION enforce_permissive_policy_on_force_rls()
RETURNS event_trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  obj RECORD;
  n INT;
BEGIN
  FOR obj IN
    SELECT * FROM pg_event_trigger_ddl_commands()
    WHERE command_tag = 'ALTER TABLE'
  LOOP
    IF EXISTS (
      SELECT 1 FROM pg_class
      WHERE oid = obj.objid AND relforcerowsecurity = true
    ) THEN
      SELECT count(*) INTO n
      FROM pg_policies
      WHERE schemaname = obj.schema_name
        AND tablename = (obj.object_identity::regclass)::text
        AND permissive = 'PERMISSIVE';
      IF n = 0 THEN
        RAISE EXCEPTION 'Cannot FORCE RLS on % - no PERMISSIVE policy exists',
          obj.object_identity;
      END IF;
    END IF;
  END LOOP;
END;
$$;

CREATE EVENT TRIGGER enforce_permissive_policy
  ON ddl_command_end
  WHEN TAG IN ('ALTER TABLE')
  EXECUTE FUNCTION enforce_permissive_policy_on_force_rls();
```

---

## Migration ordering convention

```sql
-- 1. CREATE all PERMISSIVE policies FIRST
CREATE POLICY ... ON foo ...;

-- 2. CREATE any RESTRICTIVE overlays
CREATE POLICY ... ON foo AS RESTRICTIVE ...;

-- 3. ENABLE RLS
ALTER TABLE foo ENABLE ROW LEVEL SECURITY;

-- 4. FORCE RLS LAST (Layer 2 event trigger fires here)
ALTER TABLE foo FORCE ROW LEVEL SECURITY;
```

If FORCE RLS fires before any PERMISSIVE policy exists, the event trigger blocks it.

---

## Q7 — SQL smoke harness extension (Slab 5)

Cases to add to `brain/db/tests/rls_smoke.sql`:

| # | GUC state | Target table | Expected rows |
|---|---|---|---|
| 1 | rls.role=platform_admin | any Shape A | all visible |
| 2 | rls.role=user, rls.user_id=userA UUID | Shape A | only userA |
| 3 | rls.role=child, rls.max_rating=age_8_plus | child-overlay table | only rating ≤ age_8_plus |
| 4 | All GUCs reset | any RLS table | 0 rows (fail-closed) |
| 5 | rls.role=user | Shape B | 0 rows |
| 6 | rls.role=platform_admin | Shape B | all visible |
| 7 | rls.role=user, rls.user_id=userA UUID | Shape A-FK | only messages in userA threads |
| 8 | rls.role=user, rls.user_id=userA UUID | Shape A-FK with userB parent FK | 0 rows (FK isolation) |

---

## TD-161 candidates — RLS off, has user_id

| Table | user_id type | Risk | Slab |
|---|---|---|---|
| vault_document_permissions | text | CRITICAL — controls vault access | 6b |
| alpha_workspace_users | text | Workspace membership | 6c |
| jarvis_request_log | text | Request log; currently any role can read | 6c |

All three use `text` not `uuid`. Type migration may be required. Decision deferred to Slab 6 sub-slab.

---

## Slab 6 sub-slab proposal

| Sub-slab | Scope | Priority |
|---|---|---|
| 6a | Rewrite 22 existing RLS policies to canonical Shape A / A-FK / B + verify the flagged tables | P0 |
| 6b | Add RLS to vault_document_permissions (CRITICAL) | P0 |
| 6c | Add RLS to alpha_workspace_users + jarvis_request_log | P1 |

Atomic deploy + 24h soak applies to 6a only. 6b and 6c can deploy in separate windows.

---

## Cross-references

- `~/jarvis-alpha/docs/PATTERNS.md` — pgAudit + SQLSTATE conventions (Slab 1)
- `~/jarvis-alpha/docs/SLAB2_DEPLOY_PLAN.md` — GUC namespace migration (shipped)
- Slab 4 spec (pending): SECDEF fleet + typed wrapper + LISTEN/NOTIFY rebuild + TD-94 fold-in + this doc Layer 1 CI check + Layer 2 DB event trigger
- Slab 5 spec (pending): TD-181 + Apr 27 Lock 8 + smoke harness extension
- Slab 6 spec (pending re-cut): atomic policy deploy + 24h soak with sub-slabs 6a / 6b / 6c
