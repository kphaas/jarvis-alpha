-- ============================================================
-- SLAB 5 ROLLBACK — restore legacy task_events_read policy
-- ============================================================
-- Restores the EXACT pre-canonical body (verified via pg_policies
-- query on Brain 2026-05-01):
--
--   USING: (rls.role = 'platform_admin') OR (rls.user_id IS NOT NULL)
--   WITH CHECK: NULL  (no row could be inserted/updated; admin DML
--                      went through bypassing RLS via the writer role)
--
-- This rollback file lives in brain/db/rollbacks/ (NOT migrations/)
-- per TD-183 convention. TD-184 runner filter is defense-in-depth.
-- ============================================================

BEGIN;

-- ============================================================
-- Pre-flight: confirm canonical state exists (i.e. forward
-- migration was applied)
-- ============================================================
DO $$
DECLARE
    n INT;
BEGIN
    SELECT count(*) INTO n
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'alpha_task_events'
      AND policyname = 'alpha_task_events_admin_only';
    IF n != 1 THEN
        RAISE EXCEPTION
            'Rollback pre-flight failed: canonical policy not present (n=%) - forward migration may not have been applied', n;
    END IF;
    RAISE NOTICE 'Rollback pre-flight OK';
END
$$;

-- ============================================================
-- Drop canonical, restore legacy
-- ============================================================
DROP POLICY IF EXISTS alpha_task_events_admin_only ON alpha_task_events;

CREATE POLICY task_events_read ON alpha_task_events
    AS PERMISSIVE
    FOR ALL
    USING (
        (current_setting('rls.role'::text, true) = 'platform_admin'::text)
        OR (current_setting('rls.user_id'::text, true) IS NOT NULL)
    );
-- Note: original policy had no WITH CHECK clause (NULL).
-- Recreating without WITH CHECK reproduces that behavior.

-- ============================================================
-- Post-check: legacy policy restored
-- ============================================================
DO $$
DECLARE
    n INT;
BEGIN
    SELECT count(*) INTO n
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'alpha_task_events'
      AND policyname = 'task_events_read';
    IF n != 1 THEN
        RAISE EXCEPTION
            'Rollback post-check failed: legacy policy not restored (n=%)', n;
    END IF;
    RAISE NOTICE 'Rollback post-check OK: legacy task_events_read restored';
END
$$;

COMMIT;
