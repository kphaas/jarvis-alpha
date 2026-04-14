-- Stage 6c + 6d: FORCE ROW LEVEL SECURITY on all remaining RLS tables.
--
-- Scope:
--   Step 1 — alpha_buddy_events: ENABLE + admin-only policy + FORCE
--            (table had no RLS at all prior to this migration; route
--             handlers now go through rls_connection for both reads
--             and writes, and background writers use SECDEF
--             record_buddy_event).
--   Step 2 — alpha_approval_queue + alpha_approval_audit: FORCE only
--            (ENABLE + policies landed in Stage 6b,
--             20260414_140000_approval_rls.sql).
--   Step 3 — FORCE RLS on 8 tables that already have ENABLE + policies:
--            chat_threads, chat_messages, alpha_task_graphs,
--            alpha_task_steps, alpha_task_events, alpha_dream_sessions,
--            alpha_dream_steps, alpha_watchdog_events.
--
-- After this migration every user-data table in jarvis_alpha is under
-- FORCE RLS. Bare-pool writes from background services must go through
-- SECURITY DEFINER wrappers; route handlers must go through
-- brain.db.rls.rls_connection().

BEGIN;

-- Step 1 — alpha_buddy_events (ENABLE + policy + FORCE) -------------

ALTER TABLE public.alpha_buddy_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS buddy_events_isolation ON public.alpha_buddy_events;
CREATE POLICY buddy_events_isolation ON public.alpha_buddy_events
    FOR ALL
    USING (current_setting('jarvis.role', true) = 'platform_admin')
    WITH CHECK (current_setting('jarvis.role', true) = 'platform_admin');

ALTER TABLE public.alpha_buddy_events FORCE ROW LEVEL SECURITY;

-- Step 2 — approval tables (FORCE only) -----------------------------

ALTER TABLE public.alpha_approval_queue FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_approval_audit FORCE ROW LEVEL SECURITY;

-- Step 3 — FORCE RLS on remaining tables ----------------------------

ALTER TABLE public.chat_threads          FORCE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages         FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_task_graphs     FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_task_steps      FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_task_events     FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_dream_sessions  FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_dream_steps     FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_watchdog_events FORCE ROW LEVEL SECURITY;

COMMIT;
