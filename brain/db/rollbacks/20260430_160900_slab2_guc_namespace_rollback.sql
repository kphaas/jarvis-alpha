-- =====================================================================
-- Slab 2 ROLLBACK: rls.* -> jarvis.*/app.*
--
-- Reverses 20260430_160900_slab2_guc_namespace_migration.sql.
-- Restores the 27 RLS policies to their original jarvis.*/app.* GUC
-- namespace exactly as observed via pg_policies on 2026-04-30 prior to
-- the forward migration.
--
-- This file is kept ready but NOT auto-applied. Apply only via the
-- documented Slab 2 emergency-rollback procedure (service quiesce,
-- review, manual psql -f).
--
-- Same scope as the forward migration: alpha_watchdog_events is
-- intentionally not touched.
--
-- Atomicity: BEGIN/COMMIT. Any failure rolls back all 27 changes.
-- Idempotency: pre-flight refuses if no rls.* policies remain.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- Pre-flight 1: pgaudit must still be loaded so this DDL is captured.
-- ---------------------------------------------------------------------
DO $preflight_pgaudit$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_settings
    WHERE name = 'shared_preload_libraries'
      AND setting LIKE '%pgaudit%'
  ) THEN
    RAISE EXCEPTION USING
      MESSAGE = 'pgaudit not loaded; refusing to roll back without audit trail',
      HINT    = 'Slab 1 (pgaudit) must remain installed during rollback';
  END IF;
END
$preflight_pgaudit$;

-- ---------------------------------------------------------------------
-- Pre-flight 2: at least one policy must still reference rls.*,
-- otherwise the rollback has likely already been applied.
-- ---------------------------------------------------------------------
DO $preflight_count$
DECLARE
  rls_count int;
BEGIN
  SELECT count(*) INTO rls_count
  FROM pg_policies
  WHERE schemaname = 'public'
    AND (qual LIKE '%rls.%' OR with_check LIKE '%rls.%');

  IF rls_count = 0 THEN
    RAISE EXCEPTION USING
      MESSAGE = 'No rls.* policies found; rollback may have already run',
      HINT    = 'Inspect pg_policies before retrying';
  END IF;

  RAISE NOTICE 'slab2 rollback: reverting % policies from rls.* to jarvis.*/app.*', rls_count;
END
$preflight_count$;

-- =====================================================================
-- 27 policy reversals, grouped by table.
-- Each block: DROP POLICY IF EXISTS, then CREATE POLICY with the EXACT
-- pre-migration expressions captured from pg_policies on 2026-04-30.
-- =====================================================================

-- ---- alpha_approval_audit (1) ---------------------------------------
DROP POLICY IF EXISTS approval_audit_isolation ON public.alpha_approval_audit;
CREATE POLICY approval_audit_isolation ON public.alpha_approval_audit
  AS PERMISSIVE FOR ALL
  USING ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_approval_queue (1) ---------------------------------------
DROP POLICY IF EXISTS approval_queue_isolation ON public.alpha_approval_queue;
CREATE POLICY approval_queue_isolation ON public.alpha_approval_queue
  AS PERMISSIVE FOR ALL
  USING ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_buddy_events (1) -----------------------------------------
DROP POLICY IF EXISTS buddy_events_isolation ON public.alpha_buddy_events;
CREATE POLICY buddy_events_isolation ON public.alpha_buddy_events
  AS PERMISSIVE FOR ALL
  USING ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_cloud_costs (1) ------------------------------------------
DROP POLICY IF EXISTS cloud_costs_isolation ON public.alpha_cloud_costs;
CREATE POLICY cloud_costs_isolation ON public.alpha_cloud_costs
  AS PERMISSIVE FOR ALL
  USING ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_conversation_memory (2) ----------------------------------
DROP POLICY IF EXISTS alpha_memory_isolation ON public.alpha_conversation_memory;
CREATE POLICY alpha_memory_isolation ON public.alpha_conversation_memory
  AS PERMISSIVE FOR ALL
  USING (((user_id = current_setting('jarvis.current_user'::text, true)) OR (current_setting('jarvis.role'::text, true) = 'platform_admin'::text)));

DROP POLICY IF EXISTS child_content_filter ON public.alpha_conversation_memory;
CREATE POLICY child_content_filter ON public.alpha_conversation_memory
  AS RESTRICTIVE FOR SELECT
  USING (((current_setting('jarvis.role'::text, true) <> 'child'::text) OR rating_allowed(COALESCE(content_rating, 'general'::text), current_setting('app.max_rating'::text, true))));

-- ---- alpha_dream_blocked_writes (1) ---------------------------------
DROP POLICY IF EXISTS blocked_writes_isolation ON public.alpha_dream_blocked_writes;
CREATE POLICY blocked_writes_isolation ON public.alpha_dream_blocked_writes
  AS PERMISSIVE FOR ALL
  USING ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_dream_cost_caps (1) --------------------------------------
DROP POLICY IF EXISTS cost_caps_isolation ON public.alpha_dream_cost_caps;
CREATE POLICY cost_caps_isolation ON public.alpha_dream_cost_caps
  AS PERMISSIVE FOR ALL
  USING ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_dream_cost_counters (1) ----------------------------------
DROP POLICY IF EXISTS cost_counters_isolation ON public.alpha_dream_cost_counters;
CREATE POLICY cost_counters_isolation ON public.alpha_dream_cost_counters
  AS PERMISSIVE FOR ALL
  USING ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_dream_model_policy (1) -----------------------------------
DROP POLICY IF EXISTS dream_model_policy_isolation ON public.alpha_dream_model_policy;
CREATE POLICY dream_model_policy_isolation ON public.alpha_dream_model_policy
  AS PERMISSIVE FOR ALL
  USING ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_dream_sessions (2) ---------------------------------------
DROP POLICY IF EXISTS child_profile_scope ON public.alpha_dream_sessions;
CREATE POLICY child_profile_scope ON public.alpha_dream_sessions
  AS RESTRICTIVE FOR ALL
  USING (((current_setting('jarvis.role'::text, true) <> 'child'::text) OR (owner_profile = current_setting('jarvis.current_user'::text, true))));

DROP POLICY IF EXISTS dream_sessions_platform_admin ON public.alpha_dream_sessions;
CREATE POLICY dream_sessions_platform_admin ON public.alpha_dream_sessions
  AS PERMISSIVE FOR ALL
  USING ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_dream_steps (1) ------------------------------------------
DROP POLICY IF EXISTS dream_steps_platform_admin ON public.alpha_dream_steps;
CREATE POLICY dream_steps_platform_admin ON public.alpha_dream_steps
  AS PERMISSIVE FOR ALL
  USING ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_semantic_memory (1) --------------------------------------
DROP POLICY IF EXISTS semantic_isolation ON public.alpha_semantic_memory;
CREATE POLICY semantic_isolation ON public.alpha_semantic_memory
  AS PERMISSIVE FOR ALL
  USING ((((user_id)::text = current_setting('jarvis.current_user'::text, true)) OR (current_setting('jarvis.role'::text, true) = 'platform_admin'::text)));

-- ---- alpha_system_flags (1) -----------------------------------------
DROP POLICY IF EXISTS system_flags_isolation ON public.alpha_system_flags;
CREATE POLICY system_flags_isolation ON public.alpha_system_flags
  AS PERMISSIVE FOR ALL
  USING ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_task_events (1) ------------------------------------------
DROP POLICY IF EXISTS task_events_read ON public.alpha_task_events;
CREATE POLICY task_events_read ON public.alpha_task_events
  AS PERMISSIVE FOR ALL
  USING (((current_setting('jarvis.role'::text, true) = 'platform_admin'::text) OR (current_setting('jarvis.current_user'::text, true) IS NOT NULL)));

-- ---- alpha_task_graphs (2) ------------------------------------------
DROP POLICY IF EXISTS child_profile_scope ON public.alpha_task_graphs;
CREATE POLICY child_profile_scope ON public.alpha_task_graphs
  AS RESTRICTIVE FOR ALL
  USING (((current_setting('jarvis.role'::text, true) <> 'child'::text) OR (owner_profile = current_setting('jarvis.current_user'::text, true))));

DROP POLICY IF EXISTS task_graph_isolation ON public.alpha_task_graphs;
CREATE POLICY task_graph_isolation ON public.alpha_task_graphs
  AS PERMISSIVE FOR ALL
  USING (((user_id = current_setting('jarvis.current_user'::text, true)) OR (current_setting('jarvis.role'::text, true) = 'platform_admin'::text)));

-- ---- alpha_task_steps (1) -------------------------------------------
DROP POLICY IF EXISTS task_step_isolation ON public.alpha_task_steps;
CREATE POLICY task_step_isolation ON public.alpha_task_steps
  AS PERMISSIVE FOR ALL
  USING (((user_id = current_setting('jarvis.current_user'::text, true)) OR (current_setting('jarvis.role'::text, true) = 'platform_admin'::text)));

-- ---- chat_messages (2) ----------------------------------------------
DROP POLICY IF EXISTS chat_messages_isolation ON public.chat_messages;
CREATE POLICY chat_messages_isolation ON public.chat_messages
  AS PERMISSIVE FOR ALL
  USING ((thread_id IN ( SELECT chat_threads.id
   FROM chat_threads
  WHERE (chat_threads.user_id = current_setting('jarvis.current_user'::text, true)))))
  WITH CHECK ((thread_id IN ( SELECT chat_threads.id
   FROM chat_threads
  WHERE (chat_threads.user_id = current_setting('jarvis.current_user'::text, true)))));

DROP POLICY IF EXISTS child_messages_scope ON public.chat_messages;
CREATE POLICY child_messages_scope ON public.chat_messages
  AS RESTRICTIVE FOR ALL
  USING (((current_setting('jarvis.role'::text, true) <> 'child'::text) OR (EXISTS ( SELECT 1
   FROM chat_threads t
  WHERE ((t.id = chat_messages.thread_id) AND (t.owner_profile = current_setting('jarvis.current_user'::text, true)))))));

-- ---- chat_threads (2) -----------------------------------------------
DROP POLICY IF EXISTS chat_threads_isolation ON public.chat_threads;
CREATE POLICY chat_threads_isolation ON public.chat_threads
  AS PERMISSIVE FOR ALL
  USING ((user_id = current_setting('jarvis.current_user'::text, true)))
  WITH CHECK ((user_id = current_setting('jarvis.current_user'::text, true)));

DROP POLICY IF EXISTS child_profile_scope ON public.chat_threads;
CREATE POLICY child_profile_scope ON public.chat_threads
  AS RESTRICTIVE FOR ALL
  USING (((current_setting('jarvis.role'::text, true) <> 'child'::text) OR (owner_profile = current_setting('jarvis.current_user'::text, true))));

-- ---- vault_access_log (1) -------------------------------------------
DROP POLICY IF EXISTS vault_access_log_admin ON public.vault_access_log;
CREATE POLICY vault_access_log_admin ON public.vault_access_log
  AS PERMISSIVE FOR ALL
  USING ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text));

-- ---- vault_documents (2) --------------------------------------------
DROP POLICY IF EXISTS vault_documents_read ON public.vault_documents;
CREATE POLICY vault_documents_read ON public.vault_documents
  AS PERMISSIVE FOR ALL
  USING (((classification <> '50_SECRETS'::text) AND (((current_setting('jarvis.role'::text, true) = 'platform_admin'::text) AND (classification = ANY (ARRAY['10_PUBLIC'::text, '15_KIDS'::text, '20_PROJECTS'::text, '30_FINANCE'::text, '40_PRIVATE'::text]))) OR ((current_setting('jarvis.role'::text, true) = 'user'::text) AND (classification = ANY (ARRAY['10_PUBLIC'::text, '15_KIDS'::text]))))));

DROP POLICY IF EXISTS vault_documents_write ON public.vault_documents;
CREATE POLICY vault_documents_write ON public.vault_documents
  AS PERMISSIVE FOR ALL
  USING ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text));

-- ---- vault_pipeline (1) ---------------------------------------------
DROP POLICY IF EXISTS vault_pipeline_admin ON public.vault_pipeline;
CREATE POLICY vault_pipeline_admin ON public.vault_pipeline
  AS PERMISSIVE FOR ALL
  USING ((current_setting('jarvis.role'::text, true) = 'platform_admin'::text));

-- =====================================================================
-- Post-rollback verification.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Post 1: zero policies should reference rls.* after rollback.
-- ---------------------------------------------------------------------
DO $post_no_rls$
DECLARE
  rls_remaining int;
BEGIN
  SELECT count(*) INTO rls_remaining
  FROM pg_policies
  WHERE schemaname = 'public'
    AND (qual LIKE '%rls.%' OR with_check LIKE '%rls.%');

  IF rls_remaining > 0 THEN
    RAISE EXCEPTION USING
      MESSAGE = format('%s policies still reference rls.* namespace after rollback', rls_remaining),
      HINT    = 'Rollback incomplete; review pg_policies and rerun rollback';
  END IF;

  RAISE NOTICE 'slab2 rollback: zero rls.* references remain in pg_policies';
END
$post_no_rls$;

-- ---------------------------------------------------------------------
-- Post 2: confirm jarvis.*/app.* policies are restored.
-- ---------------------------------------------------------------------
DO $post_old_count$
DECLARE
  old_count int;
BEGIN
  SELECT count(*) INTO old_count
  FROM pg_policies
  WHERE schemaname = 'public'
    AND (qual       LIKE '%jarvis.%' OR qual       LIKE '%app.%'
         OR with_check LIKE '%jarvis.%' OR with_check LIKE '%app.%');

  IF old_count < 27 THEN
    RAISE EXCEPTION USING
      MESSAGE = format('expected at least 27 jarvis.*/app.* policies after rollback, found %s', old_count),
      HINT    = 'Rollback did not restore the expected policies';
  END IF;

  RAISE NOTICE 'slab2 rollback: % policies restored to jarvis.*/app.* namespace (>= 27 expected)', old_count;
END
$post_old_count$;

COMMIT;
