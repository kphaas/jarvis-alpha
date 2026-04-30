-- =====================================================================
-- Slab 2: GUC namespace migration — jarvis.*/app.* -> rls.*
--
-- Rewrites 27 RLS policies across 21 tables to read identity/role from
-- the canonical rls.* GUC namespace. Drops and recreates each policy
-- inside a single atomic transaction.
--
-- Out of scope (intentional):
--   * alpha_watchdog_events.{watchdog_events_read, watchdog_events_system_write}
--     -- both use literal `true`, no GUC references; latent
--     watchdog_events_system_write WITH CHECK (true) bug deferred to Slab 5.
--   * Function bodies (e.g., rating_allowed) -- their GUC arguments are
--     supplied by the caller; the GUC string literal lives in the policy
--     expression which we rewrite below.
--
-- Atomicity: BEGIN/COMMIT. Any failure rolls back all 27 changes.
-- Idempotency: pre-flight refuses if no jarvis.*/app.* policies remain.
-- Reversibility: paired _rollback.sql restores the prior expressions.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- Pre-flight 1: pgaudit must be loaded so this DDL is captured in the
-- audit trail. Slab 1 installs pgaudit; refusing without it.
-- ---------------------------------------------------------------------
DO $preflight_pgaudit$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_settings
    WHERE name = 'shared_preload_libraries'
      AND setting LIKE '%pgaudit%'
  ) THEN
    RAISE EXCEPTION USING
      MESSAGE = 'pgaudit not loaded; refusing to migrate without audit trail',
      HINT    = 'Run after Slab 1 (pgaudit install) is deployed and Postgres restarted';
  END IF;
END
$preflight_pgaudit$;

-- ---------------------------------------------------------------------
-- Pre-flight 2: at least one policy must still reference the old
-- namespace, otherwise this migration has likely already been applied.
-- ---------------------------------------------------------------------
DO $preflight_count$
DECLARE
  old_ns_count int;
BEGIN
  SELECT count(*) INTO old_ns_count
  FROM pg_policies
  WHERE schemaname = 'public'
    AND (qual       LIKE '%jarvis.%' OR qual       LIKE '%app.%'
         OR with_check LIKE '%jarvis.%' OR with_check LIKE '%app.%');

  IF old_ns_count = 0 THEN
    RAISE EXCEPTION USING
      MESSAGE = 'No jarvis.*/app.* policies found; migration may have already run',
      HINT    = 'Inspect pg_policies before retrying';
  END IF;

  RAISE NOTICE 'slab2: migrating % policies from jarvis.*/app.* to rls.*', old_ns_count;
END
$preflight_count$;

-- =====================================================================
-- 27 policy rewrites, grouped by table.
-- Each block: DROP POLICY IF EXISTS, then CREATE POLICY with the EXACT
-- original expression, with only the GUC string literals renamed:
--   'jarvis.current_user' -> 'rls.user_id'
--   'jarvis.role'         -> 'rls.role'
--   'app.max_rating'      -> 'rls.max_rating'
-- =====================================================================

-- ---- alpha_approval_audit (1) ---------------------------------------
DROP POLICY IF EXISTS approval_audit_isolation ON public.alpha_approval_audit;
CREATE POLICY approval_audit_isolation ON public.alpha_approval_audit
  AS PERMISSIVE FOR ALL
  USING ((current_setting('rls.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('rls.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_approval_queue (1) ---------------------------------------
DROP POLICY IF EXISTS approval_queue_isolation ON public.alpha_approval_queue;
CREATE POLICY approval_queue_isolation ON public.alpha_approval_queue
  AS PERMISSIVE FOR ALL
  USING ((current_setting('rls.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('rls.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_buddy_events (1) -----------------------------------------
DROP POLICY IF EXISTS buddy_events_isolation ON public.alpha_buddy_events;
CREATE POLICY buddy_events_isolation ON public.alpha_buddy_events
  AS PERMISSIVE FOR ALL
  USING ((current_setting('rls.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('rls.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_cloud_costs (1) ------------------------------------------
DROP POLICY IF EXISTS cloud_costs_isolation ON public.alpha_cloud_costs;
CREATE POLICY cloud_costs_isolation ON public.alpha_cloud_costs
  AS PERMISSIVE FOR ALL
  USING ((current_setting('rls.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('rls.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_conversation_memory (2) ----------------------------------
DROP POLICY IF EXISTS alpha_memory_isolation ON public.alpha_conversation_memory;
CREATE POLICY alpha_memory_isolation ON public.alpha_conversation_memory
  AS PERMISSIVE FOR ALL
  USING (((user_id = current_setting('rls.user_id'::text, true)) OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)));

DROP POLICY IF EXISTS child_content_filter ON public.alpha_conversation_memory;
CREATE POLICY child_content_filter ON public.alpha_conversation_memory
  AS RESTRICTIVE FOR SELECT
  USING (((current_setting('rls.role'::text, true) <> 'child'::text) OR rating_allowed(COALESCE(content_rating, 'general'::text), current_setting('rls.max_rating'::text, true))));

-- ---- alpha_dream_blocked_writes (1) ---------------------------------
DROP POLICY IF EXISTS blocked_writes_isolation ON public.alpha_dream_blocked_writes;
CREATE POLICY blocked_writes_isolation ON public.alpha_dream_blocked_writes
  AS PERMISSIVE FOR ALL
  USING ((current_setting('rls.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('rls.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_dream_cost_caps (1) --------------------------------------
DROP POLICY IF EXISTS cost_caps_isolation ON public.alpha_dream_cost_caps;
CREATE POLICY cost_caps_isolation ON public.alpha_dream_cost_caps
  AS PERMISSIVE FOR ALL
  USING ((current_setting('rls.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('rls.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_dream_cost_counters (1) ----------------------------------
DROP POLICY IF EXISTS cost_counters_isolation ON public.alpha_dream_cost_counters;
CREATE POLICY cost_counters_isolation ON public.alpha_dream_cost_counters
  AS PERMISSIVE FOR ALL
  USING ((current_setting('rls.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('rls.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_dream_model_policy (1) -----------------------------------
DROP POLICY IF EXISTS dream_model_policy_isolation ON public.alpha_dream_model_policy;
CREATE POLICY dream_model_policy_isolation ON public.alpha_dream_model_policy
  AS PERMISSIVE FOR ALL
  USING ((current_setting('rls.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('rls.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_dream_sessions (2) ---------------------------------------
DROP POLICY IF EXISTS child_profile_scope ON public.alpha_dream_sessions;
CREATE POLICY child_profile_scope ON public.alpha_dream_sessions
  AS RESTRICTIVE FOR ALL
  USING (((current_setting('rls.role'::text, true) <> 'child'::text) OR (owner_profile = current_setting('rls.user_id'::text, true))));

DROP POLICY IF EXISTS dream_sessions_platform_admin ON public.alpha_dream_sessions;
CREATE POLICY dream_sessions_platform_admin ON public.alpha_dream_sessions
  AS PERMISSIVE FOR ALL
  USING ((current_setting('rls.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('rls.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_dream_steps (1) ------------------------------------------
DROP POLICY IF EXISTS dream_steps_platform_admin ON public.alpha_dream_steps;
CREATE POLICY dream_steps_platform_admin ON public.alpha_dream_steps
  AS PERMISSIVE FOR ALL
  USING ((current_setting('rls.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('rls.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_semantic_memory (1) --------------------------------------
DROP POLICY IF EXISTS semantic_isolation ON public.alpha_semantic_memory;
CREATE POLICY semantic_isolation ON public.alpha_semantic_memory
  AS PERMISSIVE FOR ALL
  USING ((((user_id)::text = current_setting('rls.user_id'::text, true)) OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)));

-- ---- alpha_system_flags (1) -----------------------------------------
DROP POLICY IF EXISTS system_flags_isolation ON public.alpha_system_flags;
CREATE POLICY system_flags_isolation ON public.alpha_system_flags
  AS PERMISSIVE FOR ALL
  USING ((current_setting('rls.role'::text, true) = 'platform_admin'::text))
  WITH CHECK ((current_setting('rls.role'::text, true) = 'platform_admin'::text));

-- ---- alpha_task_events (1) ------------------------------------------
DROP POLICY IF EXISTS task_events_read ON public.alpha_task_events;
CREATE POLICY task_events_read ON public.alpha_task_events
  AS PERMISSIVE FOR ALL
  USING (((current_setting('rls.role'::text, true) = 'platform_admin'::text) OR (current_setting('rls.user_id'::text, true) IS NOT NULL)));

-- ---- alpha_task_graphs (2) ------------------------------------------
DROP POLICY IF EXISTS child_profile_scope ON public.alpha_task_graphs;
CREATE POLICY child_profile_scope ON public.alpha_task_graphs
  AS RESTRICTIVE FOR ALL
  USING (((current_setting('rls.role'::text, true) <> 'child'::text) OR (owner_profile = current_setting('rls.user_id'::text, true))));

DROP POLICY IF EXISTS task_graph_isolation ON public.alpha_task_graphs;
CREATE POLICY task_graph_isolation ON public.alpha_task_graphs
  AS PERMISSIVE FOR ALL
  USING (((user_id = current_setting('rls.user_id'::text, true)) OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)));

-- ---- alpha_task_steps (1) -------------------------------------------
DROP POLICY IF EXISTS task_step_isolation ON public.alpha_task_steps;
CREATE POLICY task_step_isolation ON public.alpha_task_steps
  AS PERMISSIVE FOR ALL
  USING (((user_id = current_setting('rls.user_id'::text, true)) OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)));

-- ---- chat_messages (2) ----------------------------------------------
DROP POLICY IF EXISTS chat_messages_isolation ON public.chat_messages;
CREATE POLICY chat_messages_isolation ON public.chat_messages
  AS PERMISSIVE FOR ALL
  USING ((thread_id IN ( SELECT chat_threads.id
   FROM chat_threads
  WHERE (chat_threads.user_id = current_setting('rls.user_id'::text, true)))))
  WITH CHECK ((thread_id IN ( SELECT chat_threads.id
   FROM chat_threads
  WHERE (chat_threads.user_id = current_setting('rls.user_id'::text, true)))));

DROP POLICY IF EXISTS child_messages_scope ON public.chat_messages;
CREATE POLICY child_messages_scope ON public.chat_messages
  AS RESTRICTIVE FOR ALL
  USING (((current_setting('rls.role'::text, true) <> 'child'::text) OR (EXISTS ( SELECT 1
   FROM chat_threads t
  WHERE ((t.id = chat_messages.thread_id) AND (t.owner_profile = current_setting('rls.user_id'::text, true)))))));

-- ---- chat_threads (2) -----------------------------------------------
DROP POLICY IF EXISTS chat_threads_isolation ON public.chat_threads;
CREATE POLICY chat_threads_isolation ON public.chat_threads
  AS PERMISSIVE FOR ALL
  USING ((user_id = current_setting('rls.user_id'::text, true)))
  WITH CHECK ((user_id = current_setting('rls.user_id'::text, true)));

DROP POLICY IF EXISTS child_profile_scope ON public.chat_threads;
CREATE POLICY child_profile_scope ON public.chat_threads
  AS RESTRICTIVE FOR ALL
  USING (((current_setting('rls.role'::text, true) <> 'child'::text) OR (owner_profile = current_setting('rls.user_id'::text, true))));

-- ---- vault_access_log (1) -------------------------------------------
DROP POLICY IF EXISTS vault_access_log_admin ON public.vault_access_log;
CREATE POLICY vault_access_log_admin ON public.vault_access_log
  AS PERMISSIVE FOR ALL
  USING ((current_setting('rls.role'::text, true) = 'platform_admin'::text));

-- ---- vault_documents (2) --------------------------------------------
DROP POLICY IF EXISTS vault_documents_read ON public.vault_documents;
CREATE POLICY vault_documents_read ON public.vault_documents
  AS PERMISSIVE FOR ALL
  USING (((classification <> '50_SECRETS'::text) AND (((current_setting('rls.role'::text, true) = 'platform_admin'::text) AND (classification = ANY (ARRAY['10_PUBLIC'::text, '15_KIDS'::text, '20_PROJECTS'::text, '30_FINANCE'::text, '40_PRIVATE'::text]))) OR ((current_setting('rls.role'::text, true) = 'user'::text) AND (classification = ANY (ARRAY['10_PUBLIC'::text, '15_KIDS'::text]))))));

DROP POLICY IF EXISTS vault_documents_write ON public.vault_documents;
CREATE POLICY vault_documents_write ON public.vault_documents
  AS PERMISSIVE FOR ALL
  USING ((current_setting('rls.role'::text, true) = 'platform_admin'::text));

-- ---- vault_pipeline (1) ---------------------------------------------
DROP POLICY IF EXISTS vault_pipeline_admin ON public.vault_pipeline;
CREATE POLICY vault_pipeline_admin ON public.vault_pipeline
  AS PERMISSIVE FOR ALL
  USING ((current_setting('rls.role'::text, true) = 'platform_admin'::text));

-- =====================================================================
-- Post-migration verification.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Post 1: zero policies should reference jarvis.*/app.* in scope.
-- (alpha_watchdog_events is excluded because its policies use literal
-- `true` and never reference any GUC.)
-- ---------------------------------------------------------------------
DO $post_no_old$
DECLARE
  remaining int;
BEGIN
  SELECT count(*) INTO remaining
  FROM pg_policies
  WHERE schemaname = 'public'
    AND (qual       LIKE '%jarvis.%' OR qual       LIKE '%app.%'
         OR with_check LIKE '%jarvis.%' OR with_check LIKE '%app.%');

  IF remaining > 0 THEN
    RAISE EXCEPTION USING
      MESSAGE = format('%s policies still reference old jarvis.*/app.* namespace', remaining),
      HINT    = 'Migration incomplete; review pg_policies and rerun forward migration';
  END IF;

  RAISE NOTICE 'slab2: zero jarvis.*/app.* references remain in pg_policies';
END
$post_no_old$;

-- ---------------------------------------------------------------------
-- Post 2: confirm the expected number of rls.* policies are present.
-- 27 is the migration scope; allow >= 27 in case of future additions.
-- ---------------------------------------------------------------------
DO $post_rls_count$
DECLARE
  rls_count int;
BEGIN
  SELECT count(*) INTO rls_count
  FROM pg_policies
  WHERE schemaname = 'public'
    AND (qual LIKE '%rls.%' OR with_check LIKE '%rls.%');

  IF rls_count < 27 THEN
    RAISE EXCEPTION USING
      MESSAGE = format('expected at least 27 rls.* policies, found %s', rls_count),
      HINT    = 'Migration did not create the expected policies';
  END IF;

  RAISE NOTICE 'slab2: % policies now reference rls.* namespace (>= 27 expected)', rls_count;
END
$post_rls_count$;

COMMIT;
