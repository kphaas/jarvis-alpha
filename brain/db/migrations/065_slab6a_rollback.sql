-- ============================================================================
-- 065_slab6a_rollback.sql
--
-- Reverses 065_slab6a_admin_overrides_explicit_withcheck.sql.
-- Use ONLY if Phase 4 post-COMMIT issues require restoring pre-6a state.
-- Mid-transaction failures of the forward migration self-rollback (atomic);
-- this file is for committed-then-regret scenarios.
-- ============================================================================

\set ON_ERROR_STOP on
\timing on

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

SELECT pg_advisory_xact_lock(72619065);

DROP POLICY IF EXISTS chat_threads_isolation ON chat_threads;
CREATE POLICY chat_threads_isolation ON chat_threads
  FOR ALL TO PUBLIC
  USING (user_id = current_setting('rls.user_id'::text, true))
  WITH CHECK (user_id = current_setting('rls.user_id'::text, true));

DROP POLICY IF EXISTS chat_messages_isolation ON chat_messages;
CREATE POLICY chat_messages_isolation ON chat_messages
  FOR ALL TO PUBLIC
  USING (
    thread_id IN (
      SELECT chat_threads.id
      FROM chat_threads
      WHERE chat_threads.user_id = current_setting('rls.user_id'::text, true)
    )
  )
  WITH CHECK (
    thread_id IN (
      SELECT chat_threads.id
      FROM chat_threads
      WHERE chat_threads.user_id = current_setting('rls.user_id'::text, true)
    )
  );

DROP POLICY IF EXISTS alpha_memory_isolation ON alpha_conversation_memory;
CREATE POLICY alpha_memory_isolation ON alpha_conversation_memory
  FOR ALL TO PUBLIC
  USING (
    (user_id = current_setting('rls.user_id'::text, true))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  );

DROP POLICY IF EXISTS semantic_isolation ON alpha_semantic_memory;
CREATE POLICY semantic_isolation ON alpha_semantic_memory
  FOR ALL TO PUBLIC
  USING (
    (((user_id)::text = current_setting('rls.user_id'::text, true)))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  );

DROP POLICY IF EXISTS task_graph_isolation ON alpha_task_graphs;
CREATE POLICY task_graph_isolation ON alpha_task_graphs
  FOR ALL TO PUBLIC
  USING (
    (user_id = current_setting('rls.user_id'::text, true))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  );

DROP POLICY IF EXISTS task_step_isolation ON alpha_task_steps;
CREATE POLICY task_step_isolation ON alpha_task_steps
  FOR ALL TO PUBLIC
  USING (
    (user_id = current_setting('rls.user_id'::text, true))
    OR (current_setting('rls.role'::text, true) = 'platform_admin'::text)
  );

DROP POLICY IF EXISTS vault_access_log_admin ON vault_access_log;
CREATE POLICY vault_access_log_admin ON vault_access_log
  FOR ALL TO PUBLIC
  USING (current_setting('rls.role'::text, true) = 'platform_admin'::text);

DROP POLICY IF EXISTS vault_documents_write ON vault_documents;
CREATE POLICY vault_documents_write ON vault_documents
  FOR ALL TO PUBLIC
  USING (current_setting('rls.role'::text, true) = 'platform_admin'::text);

DROP POLICY IF EXISTS vault_pipeline_admin ON vault_pipeline;
CREATE POLICY vault_pipeline_admin ON vault_pipeline
  FOR ALL TO PUBLIC
  USING (current_setting('rls.role'::text, true) = 'platform_admin'::text);

DELETE FROM schema_migrations
WHERE filename = '065_slab6a_admin_overrides_explicit_withcheck.sql';

COMMIT;

\echo '=== Slab 6a rolled back ==='
\echo 'Verify: smoke harness should now show Cases 9 + 10 FAIL (admin override gone)'
\echo 'Cases 1-8 should still PASS (regression baseline restored)'
