-- Migration: 20260511_184200_slab4_phase2c_observability_cluster
-- Purpose:   Slab 4 Phase 2c — close Class A SECDEF pattern hole in the observability cluster
--            plus the composition function `run_buddy_memory_maintenance` (defensive).
-- Reference: docs/discovery/DISCOVERY_2026-05-11_slab4_phase1a_secdef_audit.md (§5 HIGH + §6 step 3)
-- Functions: record_buddy_event, record_watchdog_event, run_buddy_memory_maintenance.
-- Body diff: One inserted PERFORM line at top of each function body.
-- Notes on run_buddy_memory_maintenance:
--   This is a composition fn. After Track B (memory cluster) lands, the inner SECDEF
--   functions it delegates to are themselves rls.role-setting. The composition also
--   gets the set_config line defensively, so it's self-sufficient when invoked from
--   contexts (cron, buddy agent) that may not have rls.role pre-set.

-- -------------------------------------------------------------------------
-- 1. record_buddy_event
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.record_buddy_event(p_user_id text, p_event_type text, p_title text, p_body text, p_priority integer, p_source text, p_payload jsonb)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
  v_id UUID;
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  -- event_type must match CHECK constraint: alert | reminder | suggestion | system
  -- priority integer scale: 1=low, 2=normal, 3=high
  -- user_id is nullable per schema; 'system' sentinel convention per PATTERNS.md §15

  INSERT INTO public.alpha_buddy_events
    (user_id, event_type, title, body, priority, source, payload)
  VALUES
    (p_user_id, p_event_type, p_title, p_body, p_priority, p_source, p_payload)
  RETURNING id INTO v_id;

  RETURN v_id;
EXCEPTION
  WHEN OTHERS THEN
    -- Audit-critical: re-raise all errors
    RAISE;
END;
$function$;

-- -------------------------------------------------------------------------
-- 2. record_watchdog_event
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.record_watchdog_event(p_service_name text, p_node text, p_event_type text, p_previous_state text, p_current_state text, p_consecutive_failures integer, p_latency_ms numeric, p_http_status integer, p_error_message text, p_action_taken text, p_trace_id uuid)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    v_id uuid;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '5s';

    INSERT INTO public.alpha_watchdog_events
        (service_name, node, event_type, previous_state, current_state,
         consecutive_failures, latency_ms, http_status, error_message,
         action_taken, trace_id)
    VALUES (
        p_service_name, p_node, p_event_type, p_previous_state, p_current_state,
        p_consecutive_failures, p_latency_ms, p_http_status, p_error_message,
        p_action_taken, p_trace_id
    )
    RETURNING id INTO v_id;

    RETURN v_id;

EXCEPTION
    WHEN check_violation THEN
        RAISE WARNING 'record_watchdog_event invalid event_type=% (SQLSTATE=%)', p_event_type, SQLSTATE;
        RETURN NULL;
    WHEN sqlstate '40001' OR sqlstate '40P01' THEN
        RAISE;
    WHEN OTHERS THEN
        RAISE WARNING 'record_watchdog_event failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
        RETURN NULL;
END;
$function$;

-- -------------------------------------------------------------------------
-- 3. run_buddy_memory_maintenance (composition — defensive set_config)
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.run_buddy_memory_maintenance(p_user_id text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
  v_evicted_working INTEGER := 0;
  v_evicted_episodic INTEGER := 0;
  v_capped_episodic INTEGER := 0;
  v_capped_semantic INTEGER := 0;
  v_errors JSONB := '[]'::jsonb;
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '60s';

  IF p_user_id IS NULL OR p_user_id = '' THEN
    RAISE EXCEPTION 'run_buddy_memory_maintenance: p_user_id required' USING ERRCODE = '22023';
  END IF;

  -- Step 1: evict expired working memory (global op, not user-scoped)
  BEGIN
    v_evicted_working := public.evict_expired_working_memory();
  EXCEPTION WHEN OTHERS THEN
    v_errors := v_errors || jsonb_build_object('step', 'evict_working', 'error', SQLERRM);
  END;

  -- Step 2: evict episodic older than 30 days
  BEGIN
    v_evicted_episodic := public.evict_episodic_memory_older_than(p_user_id, 30);
  EXCEPTION WHEN OTHERS THEN
    v_errors := v_errors || jsonb_build_object('step', 'evict_episodic', 'error', SQLERRM);
  END;

  -- Step 3: cap episodic at 1000 rows
  BEGIN
    v_capped_episodic := public.cap_episodic_memory(p_user_id, 1000);
  EXCEPTION WHEN OTHERS THEN
    v_errors := v_errors || jsonb_build_object('step', 'cap_episodic', 'error', SQLERRM);
  END;

  -- Step 4: cap semantic at 200 rows
  BEGIN
    v_capped_semantic := public.cap_semantic_memory(p_user_id, 200);
  EXCEPTION WHEN OTHERS THEN
    v_errors := v_errors || jsonb_build_object('step', 'cap_semantic', 'error', SQLERRM);
  END;

  -- NOTE: promote step removed 20260408_150000 — see TD-40

  RETURN jsonb_build_object(
    'user_id', p_user_id,
    'evicted_working', v_evicted_working,
    'evicted_episodic', v_evicted_episodic,
    'capped_episodic', v_capped_episodic,
    'capped_semantic', v_capped_semantic,
    'errors', v_errors
  );
END;
$function$;

-- -------------------------------------------------------------------------
-- POST-FLIGHT 1: introspection
-- -------------------------------------------------------------------------
DO $$
DECLARE
    v_fn text;
    v_names text[] := ARRAY[
        'record_buddy_event',
        'record_watchdog_event',
        'run_buddy_memory_maintenance'
    ];
BEGIN
    FOREACH v_fn IN ARRAY v_names LOOP
        IF NOT EXISTS (
            SELECT 1
              FROM pg_proc
             WHERE proname = v_fn
               AND pronamespace = 'public'::regnamespace
               AND pg_get_functiondef(oid) LIKE '%set_config(''rls.role'', ''platform_admin'', true)%'
        ) THEN
            RAISE EXCEPTION 'POST-FLIGHT introspect FAILED: % missing set_config line', v_fn;
        END IF;
        RAISE NOTICE 'POST-FLIGHT introspect: % contains rls.role set_config OK', v_fn;
    END LOOP;
END $$;

-- -------------------------------------------------------------------------
-- POST-FLIGHT 2: functional smoke under jarvis_alpha_writer in a savepoint.
-- -------------------------------------------------------------------------
SAVEPOINT verify_functional;

SET LOCAL ROLE jarvis_alpha_writer;

DO $$
DECLARE
    v_id    uuid;
    v_jsonb jsonb;
BEGIN
    -- record_buddy_event: event_type must be alert|reminder|suggestion|system
    BEGIN
        v_id := public.record_buddy_event(
            'post-flight-test-user',
            'system',
            'POST-FLIGHT test title',
            'POST-FLIGHT test body — rolled back',
            2,
            'post-flight',
            '{"verification": true}'::jsonb
        );
        RAISE NOTICE 'POST-FLIGHT functional: record_buddy_event OK (id=%)', v_id;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: record_buddy_event FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;

    -- record_watchdog_event: event_type must be down|restored|degraded|restart_triggered|
    --   restart_succeeded|restart_failed|check_error
    BEGIN
        v_id := public.record_watchdog_event(
            'post-flight-service',
            'post-flight-node',
            'check_error',
            'unknown',
            'unknown',
            0,
            NULL::numeric,
            NULL::integer,
            'POST-FLIGHT verification — rolled back',
            'noop',
            NULL::uuid
        );
        RAISE NOTICE 'POST-FLIGHT functional: record_watchdog_event OK (id=%)', v_id;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: record_watchdog_event FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;

    -- run_buddy_memory_maintenance: bogus user → all inner steps return 0.
    -- Note: inner SECDEF callees were patched in Track B; this composition
    -- then delegates safely. Function returns jsonb summary.
    BEGIN
        v_jsonb := public.run_buddy_memory_maintenance('post-flight-test-user');
        RAISE NOTICE 'POST-FLIGHT functional: run_buddy_memory_maintenance OK (result=%)', v_jsonb;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: run_buddy_memory_maintenance FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;
END $$;

RESET ROLE;

ROLLBACK TO SAVEPOINT verify_functional;
