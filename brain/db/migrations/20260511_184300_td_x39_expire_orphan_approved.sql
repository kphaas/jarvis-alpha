-- Migration: 20260511_184300_td_x39_expire_orphan_approved
-- Purpose:   New SECURITY DEFINER cleanup function — transitions rows that are
--            'approved' but past their expiry to status='expired' without ever
--            being executed. Intended for periodic invocation via Buddy agent
--            or LaunchAgent cron.
-- TD:        TD-X39 (renumbered cleanup; tracking issue to be filed alongside)
-- Wiring:    NOT invoked by anything yet. Wiring into buddy_agent or a cron
--            LaunchAgent is a follow-up TD.
-- Today:     8 orphan rows exist in prod per TD-211 work; calling this function
--            once after deploy cleans them.

-- -------------------------------------------------------------------------
-- 1. expire_orphan_approved_rows
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.expire_orphan_approved_rows()
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    v_count integer;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    -- Transition rows that are approved but expired to status='expired'
    UPDATE public.alpha_approval_queue
    SET status = 'expired',
        executed_at = NULL
    WHERE status = 'approved'
      AND expires_at < NOW()
      AND executed_at IS NULL;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$function$;

COMMENT ON FUNCTION public.expire_orphan_approved_rows IS
'Transitions stuck-approved rows past expiry to status=expired. Intended for periodic invocation via Buddy or LaunchAgent cron. TD-X39.';

-- -------------------------------------------------------------------------
-- POST-FLIGHT 1: introspection — function exists, has the set_config line,
-- and is SECURITY DEFINER.
-- -------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_proc
         WHERE proname = 'expire_orphan_approved_rows'
           AND pronamespace = 'public'::regnamespace
           AND prosecdef = true
           AND pg_get_functiondef(oid) LIKE '%set_config(''rls.role'', ''platform_admin'', true)%'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT introspect FAILED: expire_orphan_approved_rows missing SECDEF or set_config line';
    END IF;
    RAISE NOTICE 'POST-FLIGHT introspect: expire_orphan_approved_rows is SECDEF + contains set_config OK';
END $$;

-- -------------------------------------------------------------------------
-- POST-FLIGHT 2: functional smoke under jarvis_alpha_writer, in a savepoint
-- that is rolled back. Calling the function on a test DB will UPDATE any
-- legitimately-orphan rows; the savepoint discards those updates.
-- -------------------------------------------------------------------------
SAVEPOINT verify_functional;

SET LOCAL ROLE jarvis_alpha_writer;

DO $$
DECLARE
    v_count integer;
BEGIN
    BEGIN
        v_count := public.expire_orphan_approved_rows();
        RAISE NOTICE 'POST-FLIGHT functional: expire_orphan_approved_rows OK (rows=%)', v_count;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: expire_orphan_approved_rows FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;
END $$;

RESET ROLE;

ROLLBACK TO SAVEPOINT verify_functional;
