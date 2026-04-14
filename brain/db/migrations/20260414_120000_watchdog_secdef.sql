-- Stage 7: SECURITY DEFINER wrapper for watchdog event writes
-- Removes dependency on rls.user_id GUC legacy convention
-- Matches alpha_watchdog_events column list exactly

BEGIN;

CREATE OR REPLACE FUNCTION public.record_watchdog_event(
    p_service_name text,
    p_node text,
    p_event_type text,
    p_previous_state text,
    p_current_state text,
    p_consecutive_failures integer,
    p_latency_ms numeric,
    p_http_status integer,
    p_error_message text,
    p_action_taken text,
    p_trace_id uuid
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
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
    );

EXCEPTION
    WHEN check_violation THEN
        RAISE WARNING 'record_watchdog_event invalid event_type=% (SQLSTATE=%)', p_event_type, SQLSTATE;
    WHEN sqlstate '40001' OR sqlstate '40P01' THEN
        RAISE;
    WHEN OTHERS THEN
        RAISE WARNING 'record_watchdog_event failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
END;
$$;

REVOKE ALL ON FUNCTION public.record_watchdog_event(text,text,text,text,text,integer,numeric,integer,text,text,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.record_watchdog_event(text,text,text,text,text,integer,numeric,integer,text,text,uuid) TO jarvis_alpha_app;
GRANT EXECUTE ON FUNCTION public.record_watchdog_event(text,text,text,text,text,integer,numeric,integer,text,text,uuid) TO jarvis_alpha_writer;

COMMIT;
