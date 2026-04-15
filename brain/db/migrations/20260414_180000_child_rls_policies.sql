-- Migration: 20260414_180000_child_rls_policies
-- Purpose: Child-safe RLS SELECT policies on 5 tables

BEGIN;

-- 1. alpha_conversation_memory — content filter
CREATE POLICY child_content_filter ON alpha_conversation_memory
    AS RESTRICTIVE
    FOR SELECT
    TO jarvis_alpha_app
    USING (
        current_setting('jarvis.role', true) <> 'child'
        OR rating_allowed(
            COALESCE(content_rating, 'general'),
            current_setting('app.max_rating', true)
        )
    );

-- 2. chat_threads — profile scope
CREATE POLICY child_profile_scope ON chat_threads
    AS RESTRICTIVE
    FOR ALL
    TO jarvis_alpha_app
    USING (
        current_setting('jarvis.role', true) <> 'child'
        OR owner_profile = current_setting('jarvis.current_user', true)
    );

-- 3. chat_messages — scoped via thread owner_profile join
CREATE POLICY child_messages_scope ON chat_messages
    AS RESTRICTIVE
    FOR ALL
    TO jarvis_alpha_app
    USING (
        current_setting('jarvis.role', true) <> 'child'
        OR EXISTS (
            SELECT 1 FROM chat_threads t
            WHERE t.id = chat_messages.thread_id
            AND t.owner_profile = current_setting('jarvis.current_user', true)
        )
    );

-- 4. alpha_task_graphs — profile scope
CREATE POLICY child_profile_scope ON alpha_task_graphs
    AS RESTRICTIVE
    FOR ALL
    TO jarvis_alpha_app
    USING (
        current_setting('jarvis.role', true) <> 'child'
        OR owner_profile = current_setting('jarvis.current_user', true)
    );

-- 5. alpha_dream_sessions — profile scope
CREATE POLICY child_profile_scope ON alpha_dream_sessions
    AS RESTRICTIVE
    FOR ALL
    TO jarvis_alpha_app
    USING (
        current_setting('jarvis.role', true) <> 'child'
        OR owner_profile = current_setting('jarvis.current_user', true)
    );

COMMIT;
