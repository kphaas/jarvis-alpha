-- ============================================================
-- SLAB 5 — alpha_task_events canonical Shape B policy
-- ============================================================
-- Closes Apr 27 Lock 8: legacy task_events_read policy granted
-- read access to ANY authenticated user via "rls.user_id IS NOT NULL"
-- clause. Canonical Shape B template (per SLAB3_POLICY_TEMPLATE.md)
-- restricts to platform_admin only.
--
-- TD-181 fix shipped in same commit (brain/tasks/executor.py).
-- TD-191 captured: doc/DB drift in Apr 27 Lock 8 description.
-- TD-183 lesson applied: rollback file in brain/db/rollbacks/
-- (outside runner scan path); TD-184 filter as defense-in-depth.
-- ============================================================

BEGIN;

-- ============================================================
-- Pre-flight: confirm we are in the expected legacy state
-- ============================================================
DO $$
DECLARE
    n INT;
BEGIN
    -- Expect exactly 1 policy named task_events_read
    SELECT count(*) INTO n
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'alpha_task_events'
      AND policyname = 'task_events_read';
    IF n != 1 THEN
        RAISE EXCEPTION
            'Pre-flight failed: expected 1 task_events_read policy, found %', n;
    END IF;

    -- Expect canonical policy NOT yet present
    SELECT count(*) INTO n
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'alpha_task_events'
      AND policyname = 'alpha_task_events_admin_only';
    IF n != 0 THEN
        RAISE EXCEPTION
            'Pre-flight failed: canonical policy already exists (n=%) - is migration already applied?', n;
    END IF;

    RAISE NOTICE 'Pre-flight OK: legacy task_events_read present, canonical policy absent';
END
$$;

-- ============================================================
-- Drop legacy policy (current body: platform_admin OR rls.user_id IS NOT NULL)
-- ============================================================
DROP POLICY IF EXISTS task_events_read ON alpha_task_events;

-- ============================================================
-- Install canonical Shape B (per SLAB3_POLICY_TEMPLATE.md)
-- ============================================================
CREATE POLICY alpha_task_events_admin_only ON alpha_task_events
    AS PERMISSIVE
    FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

-- alpha_task_events already has FORCE RLS enabled (per Slab 3 inventory)
-- No ALTER TABLE needed.

-- ============================================================
-- Post-check: confirm canonical state
-- ============================================================
DO $$
DECLARE
    n INT;
BEGIN
    -- Canonical policy installed
    SELECT count(*) INTO n
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'alpha_task_events'
      AND policyname = 'alpha_task_events_admin_only'
      AND permissive = 'PERMISSIVE'
      AND cmd = 'ALL';
    IF n != 1 THEN
        RAISE EXCEPTION
            'Post-check failed: canonical alpha_task_events_admin_only policy not installed (n=%)', n;
    END IF;

    -- Legacy policy gone
    SELECT count(*) INTO n
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'alpha_task_events'
      AND policyname = 'task_events_read';
    IF n != 0 THEN
        RAISE EXCEPTION
            'Post-check failed: legacy task_events_read still exists (n=%)', n;
    END IF;

    -- Q6 invariant: at least one PERMISSIVE policy exists
    SELECT count(*) INTO n
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'alpha_task_events'
      AND permissive = 'PERMISSIVE';
    IF n < 1 THEN
        RAISE EXCEPTION
            'Post-check failed: Q6 invariant violated - no PERMISSIVE policy on alpha_task_events';
    END IF;

    RAISE NOTICE 'Post-check OK: canonical Shape B installed, legacy gone, Q6 invariant holds';
END
$$;

COMMIT;
