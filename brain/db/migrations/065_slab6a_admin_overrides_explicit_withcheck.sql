-- ============================================================================
-- 065_slab6a_admin_overrides_explicit_withcheck.sql
--
-- Slab 6a — 9 RLS policy changes:
--   2 admin overrides added (chat_threads_isolation, chat_messages_isolation)
--   7 explicit with_check additions (mirrors existing qual)
--
-- References:
--   docs/handoffs/HANDOFF_2026-05-07_01.md §"SLAB 6A FINAL SCOPE — 9 POLICIES"
--   docs/SLAB6_DEPLOY_PLAN.md
--
-- Applied direct via psql (bypasses migration runner per Q2=A on 2026-05-08).
-- schema_migrations row inserted in same transaction to keep tracking honest.
--
-- Atomic transaction. lock_timeout 5s. statement_timeout 30s. pg_advisory_xact_lock.
-- Failure of ANY policy change rolls back ALL.
-- ============================================================================

\set ON_ERROR_STOP on
\timing on

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SET LOCAL idle_in_transaction_session_timeout = '60s';

SELECT pg_advisory_xact_lock(72619065);

DO $$
DECLARE
  v_table TEXT;
  v_force BOOL;
  v_targets TEXT[] := ARRAY[
    'chat_threads', 'chat_messages',
    'alpha_conversation_memory', 'alpha_semantic_memory',
    'alpha_task_graphs', 'alpha_task_steps',
    'vault_access_log', 'vault_documents', 'vault_pipeline'
  ];
BEGIN
  FOREACH v_table IN ARRAY v_targets LOOP
    SELECT relforcerowsecurity INTO v_force
    FROM pg_class
    WHERE relname = v_table AND relnamespace = 'public'::regnamespace;

    IF v_force IS NULL THEN
      RAISE EXCEPTION 'PRE-FLIGHT FAIL: table public.% not found', v_table;
    END IF;
    IF NOT v_force THEN
      RAISE EXCEPTION 'PRE-FLIGHT FAIL: table public.% does NOT have FORCE RLS', v_table;
    END IF;
  END LOOP;
  RAISE NOTICE 'PRE-FLIGHT PASS: all 9 target tables verified with FORCE RLS';
END $$;

DROP POLICY IF EXISTS chat_threads_isolation ON chat_threads;
CREATE POLICY chat_threads_isolation ON chat_threads
  FOR ALL TO PUBLIC
  USING (
    (user_id = current_setting('rls.user_id'::text, true))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  )
  WITH CHECK (
    (user_id = current_setting('rls.user_id'::text, true))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  );

DROP POLICY IF EXISTS chat_messages_isolation ON chat_messages;
CREATE POLICY chat_messages_isolation ON chat_messages
  FOR ALL TO PUBLIC
  USING (
    (thread_id IN (
      SELECT chat_threads.id
      FROM chat_threads
      WHERE chat_threads.user_id = current_setting('rls.user_id'::text, true)
    ))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  )
  WITH CHECK (
    (thread_id IN (
      SELECT chat_threads.id
      FROM chat_threads
      WHERE chat_threads.user_id = current_setting('rls.user_id'::text, true)
    ))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  );

DROP POLICY IF EXISTS alpha_memory_isolation ON alpha_conversation_memory;
CREATE POLICY alpha_memory_isolation ON alpha_conversation_memory
  FOR ALL TO PUBLIC
  USING (
    (user_id = current_setting('rls.user_id'::text, true))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  )
  WITH CHECK (
    (user_id = current_setting('rls.user_id'::text, true))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  );

DROP POLICY IF EXISTS semantic_isolation ON alpha_semantic_memory;
CREATE POLICY semantic_isolation ON alpha_semantic_memory
  FOR ALL TO PUBLIC
  USING (
    (((user_id)::text = current_setting('rls.user_id'::text, true)))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  )
  WITH CHECK (
    (((user_id)::text = current_setting('rls.user_id'::text, true)))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  );

DROP POLICY IF EXISTS task_graph_isolation ON alpha_task_graphs;
CREATE POLICY task_graph_isolation ON alpha_task_graphs
  FOR ALL TO PUBLIC
  USING (
    (user_id = current_setting('rls.user_id'::text, true))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  )
  WITH CHECK (
    (user_id = current_setting('rls.user_id'::text, true))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  );

DROP POLICY IF EXISTS task_step_isolation ON alpha_task_steps;
CREATE POLICY task_step_isolation ON alpha_task_steps
  FOR ALL TO PUBLIC
  USING (
    (user_id = current_setting('rls.user_id'::text, true))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  )
  WITH CHECK (
    (user_id = current_setting('rls.user_id'::text, true))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  );

DROP POLICY IF EXISTS vault_access_log_admin ON vault_access_log;
CREATE POLICY vault_access_log_admin ON vault_access_log
  FOR ALL TO PUBLIC
  USING (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  WITH CHECK (current_setting('rls.role'::text, true) = 'platform_admin'::text);

DROP POLICY IF EXISTS vault_documents_write ON vault_documents;
CREATE POLICY vault_documents_write ON vault_documents
  FOR ALL TO PUBLIC
  USING (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  WITH CHECK (current_setting('rls.role'::text, true) = 'platform_admin'::text);

DROP POLICY IF EXISTS vault_pipeline_admin ON vault_pipeline;
CREATE POLICY vault_pipeline_admin ON vault_pipeline
  FOR ALL TO PUBLIC
  USING (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  WITH CHECK (current_setting('rls.role'::text, true) = 'platform_admin'::text);

DO $$
DECLARE
  v_count INT;
  v_overrides INT;
BEGIN
  SELECT count(*) INTO v_count
  FROM pg_policies
  WHERE policyname IN (
    'chat_threads_isolation','chat_messages_isolation',
    'alpha_memory_isolation','semantic_isolation',
    'task_graph_isolation','task_step_isolation',
    'vault_access_log_admin','vault_documents_write','vault_pipeline_admin'
  )
  AND with_check IS NOT NULL;

  IF v_count <> 9 THEN
    RAISE EXCEPTION 'POST-FLIGHT FAIL: expected 9 policies with non-NULL with_check, got %', v_count;
  END IF;

  SELECT count(*) INTO v_overrides
  FROM pg_policies
  WHERE policyname IN ('chat_threads_isolation','chat_messages_isolation')
  AND qual LIKE '%platform_admin%';

  IF v_overrides <> 2 THEN
    RAISE EXCEPTION 'POST-FLIGHT FAIL: expected 2 admin-override policies, got %', v_overrides;
  END IF;

  RAISE NOTICE 'POST-FLIGHT PASS: 9 policies have explicit with_check, 2 have admin override';
END $$;

INSERT INTO schema_migrations (filename, checksum, source)
VALUES (
  '065_slab6a_admin_overrides_explicit_withcheck.sql',
  :'checksum',
  'runner'
)
ON CONFLICT (filename) DO UPDATE
  SET checksum = EXCLUDED.checksum,
      applied_at = NOW();

COMMIT;

\echo '=== Slab 6a applied successfully ==='
\echo 'Next: bash ~/jarvis-alpha/scripts/run_smoke.sh prod'
\echo 'Expected: all 10 cases PASS (Cases 9 + 10 now valid; were N/A pre-6a)'
