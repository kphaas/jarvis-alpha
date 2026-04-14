-- 20260414_130000_guc_canonicalize.sql
--
-- Stage 6a — GUC namespace canonicalization.
--
-- Eliminates legacy GUC families app.profile_role, app.profile_id, and
-- rls.user_id from every live RLS policy that still references them.
-- After this migration, the only identity GUCs read by any policy are
-- jarvis.current_user and jarvis.role ('platform_admin' | 'user').
--
-- Coordinated with Python-side changes in this same commit:
--   brain/db/rls.py          — stops setting the three legacy GUCs
--   brain/routes/watchdog.py — switches to record_watchdog_event() SECDEF
--   brain/routes/dev.py      — maps raw role → canonical jarvis.role value
--
-- Also returns uuid from record_watchdog_event() so the ingest route can
-- echo the inserted id to its caller.
--
-- Policies that were already canonical in the live DB are NOT touched:
--   task_graph_isolation    (alpha_task_graphs)
--   task_step_isolation     (alpha_task_steps)
--   task_events_read        (alpha_task_events)
--   child_memory_rating     (alpha_conversation_memory — uses app.max_rating, OOS)
--   child_memory_write      (alpha_conversation_memory)
--
-- Frozen migrations 006/008b/009/012/014/015 are NOT touched.
--
-- Note on app.max_rating / app.workspace_id: explicitly OUT of scope. Those
-- two app.* GUCs continue to be set by rls.py and read by the content-rating
-- and workspace-scoping policies untouched here.

BEGIN;

-- ============================================================
-- 1. record_watchdog_event — return uuid (was: void)
-- ============================================================

DROP FUNCTION IF EXISTS public.record_watchdog_event(
    text, text, text, text, text, integer, numeric, integer, text, text, uuid
);

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
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_id uuid;
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
$$;

REVOKE ALL ON FUNCTION public.record_watchdog_event(
    text, text, text, text, text, integer, numeric, integer, text, text, uuid
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.record_watchdog_event(
    text, text, text, text, text, integer, numeric, integer, text, text, uuid
) TO jarvis_alpha_app;
GRANT EXECUTE ON FUNCTION public.record_watchdog_event(
    text, text, text, text, text, integer, numeric, integer, text, text, uuid
) TO jarvis_alpha_writer;

-- ============================================================
-- 2. alpha_task_graphs — child_task_isolation only
--    task_graph_isolation already canonical; leave alone.
-- ============================================================

DROP POLICY IF EXISTS child_task_isolation ON alpha_task_graphs;
CREATE POLICY child_task_isolation ON alpha_task_graphs
    USING (current_setting('jarvis.role', TRUE) = 'platform_admin');

-- ============================================================
-- 3. alpha_dream_sessions — child_dream_isolation
-- ============================================================

DROP POLICY IF EXISTS child_dream_isolation ON alpha_dream_sessions;
CREATE POLICY child_dream_isolation ON alpha_dream_sessions
    USING (current_setting('jarvis.role', TRUE) = 'platform_admin');

-- ============================================================
-- 4. alpha_dream_steps — child_dream_step_isolation
-- ============================================================

DROP POLICY IF EXISTS child_dream_step_isolation ON alpha_dream_steps;
CREATE POLICY child_dream_step_isolation ON alpha_dream_steps
    USING (current_setting('jarvis.role', TRUE) = 'platform_admin');

-- ============================================================
-- 5. chat_threads — chat_threads_isolation + child_thread_isolation
-- ============================================================

DROP POLICY IF EXISTS chat_threads_isolation ON chat_threads;
CREATE POLICY chat_threads_isolation ON chat_threads
    USING (user_id = current_setting('jarvis.current_user', TRUE))
    WITH CHECK (user_id = current_setting('jarvis.current_user', TRUE));

DROP POLICY IF EXISTS child_thread_isolation ON chat_threads;
CREATE POLICY child_thread_isolation ON chat_threads
    USING (
        current_setting('jarvis.role', TRUE) = 'platform_admin'
        OR owner_profile = current_setting('jarvis.current_user', TRUE)
    )
    WITH CHECK (
        current_setting('jarvis.role', TRUE) = 'platform_admin'
        OR owner_profile = current_setting('jarvis.current_user', TRUE)
    );

-- ============================================================
-- 6. chat_messages — chat_messages_isolation + child_message_isolation
--                    + child_content_rating (app.max_rating OOS, kept)
-- ============================================================

DROP POLICY IF EXISTS chat_messages_isolation ON chat_messages;
CREATE POLICY chat_messages_isolation ON chat_messages
    USING (thread_id IN (
        SELECT id FROM chat_threads
        WHERE user_id = current_setting('jarvis.current_user', TRUE)
    ))
    WITH CHECK (thread_id IN (
        SELECT id FROM chat_threads
        WHERE user_id = current_setting('jarvis.current_user', TRUE)
    ));

DROP POLICY IF EXISTS child_message_isolation ON chat_messages;
CREATE POLICY child_message_isolation ON chat_messages
    USING (
        current_setting('jarvis.role', TRUE) = 'platform_admin'
        OR thread_id IN (
            SELECT id FROM chat_threads
            WHERE owner_profile = current_setting('jarvis.current_user', TRUE)
        )
    )
    WITH CHECK (
        current_setting('jarvis.role', TRUE) = 'platform_admin'
        OR thread_id IN (
            SELECT id FROM chat_threads
            WHERE owner_profile = current_setting('jarvis.current_user', TRUE)
        )
    );

DROP POLICY IF EXISTS child_content_rating ON chat_messages;
CREATE POLICY child_content_rating ON chat_messages
    FOR SELECT
    USING (
        current_setting('jarvis.role', TRUE) = 'platform_admin'
        OR rating_level(content_rating) <= rating_level(current_setting('app.max_rating', TRUE))
    );

-- ============================================================
-- 7. vault_documents / vault_pipeline / vault_access_log — was 014
--    Map old 'admin' → 'platform_admin', old 'child' → 'user'.
-- ============================================================

DROP POLICY IF EXISTS vault_documents_read ON vault_documents;
CREATE POLICY vault_documents_read ON vault_documents
    USING (
        classification <> '50_SECRETS'
        AND (
            (current_setting('jarvis.role', TRUE) = 'platform_admin'
             AND classification = ANY(ARRAY['10_PUBLIC','15_KIDS','20_PROJECTS','30_FINANCE','40_PRIVATE']))
            OR
            (current_setting('jarvis.role', TRUE) = 'user'
             AND classification = ANY(ARRAY['10_PUBLIC','15_KIDS']))
        )
    );

DROP POLICY IF EXISTS vault_documents_write ON vault_documents;
CREATE POLICY vault_documents_write ON vault_documents
    USING (current_setting('jarvis.role', TRUE) = 'platform_admin');

DROP POLICY IF EXISTS vault_pipeline_admin ON vault_pipeline;
CREATE POLICY vault_pipeline_admin ON vault_pipeline
    USING (current_setting('jarvis.role', TRUE) = 'platform_admin');

DROP POLICY IF EXISTS vault_access_log_admin ON vault_access_log;
CREATE POLICY vault_access_log_admin ON vault_access_log
    USING (current_setting('jarvis.role', TRUE) = 'platform_admin');

-- ============================================================
-- 8. alpha_watchdog_events — was 012
--    Writes now flow exclusively through public.record_watchdog_event()
--    SECURITY DEFINER. The legacy rls.user_id='system' GUC convention is
--    gone. Replace the write policy with a permissive WITH CHECK (true)
--    since the SECDEF wrapper is the only sanctioned write path and the
--    wrapper itself enforces validation.
-- ============================================================

DROP POLICY IF EXISTS watchdog_events_system_write ON alpha_watchdog_events;
CREATE POLICY watchdog_events_system_write ON alpha_watchdog_events
    FOR INSERT
    WITH CHECK (true);

COMMIT;
