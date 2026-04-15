-- Migration: 20260415_110000_td60_drop_legacy_child_policies
-- Purpose: TD-60 — drop 8 legacy PERMISSIVE child policies superseded by
--          RESTRICTIVE policies added in session 2026-04-14 #04
-- Risk: NONE — all dropped policies are PERMISSIVE; RESTRICTIVE policies remain

BEGIN;

DROP POLICY IF EXISTS child_memory_rating        ON alpha_conversation_memory;
DROP POLICY IF EXISTS child_memory_write         ON alpha_conversation_memory;
DROP POLICY IF EXISTS child_dream_isolation      ON alpha_dream_sessions;
DROP POLICY IF EXISTS child_dream_step_isolation ON alpha_dream_steps;
DROP POLICY IF EXISTS child_task_isolation       ON alpha_task_graphs;
DROP POLICY IF EXISTS child_content_rating       ON chat_messages;
DROP POLICY IF EXISTS child_message_isolation    ON chat_messages;
DROP POLICY IF EXISTS child_thread_isolation     ON chat_threads;

COMMIT;
