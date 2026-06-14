-- ADR-0026 PR-2: archive_working executor, revert, and Buddy hold precedence.
-- Scope: archive working memory only. No semantic promotion/demotion executor.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260614120000);

ALTER TABLE public.alpha_conversation_memory
    ADD COLUMN IF NOT EXISTS consolidation_hold BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS consolidation_hold_proposal_id UUID,
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS archived_by_proposal_id UUID;

DO $constraints$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'alpha_conversation_memory_hold_proposal_fkey'
           AND conrelid = 'public.alpha_conversation_memory'::regclass
    ) THEN
        ALTER TABLE public.alpha_conversation_memory
            ADD CONSTRAINT alpha_conversation_memory_hold_proposal_fkey
            FOREIGN KEY (consolidation_hold_proposal_id)
            REFERENCES public.alpha_memory_consolidation_proposals(id)
            ON DELETE SET NULL;
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'alpha_conversation_memory_archived_by_proposal_fkey'
           AND conrelid = 'public.alpha_conversation_memory'::regclass
    ) THEN
        ALTER TABLE public.alpha_conversation_memory
            ADD CONSTRAINT alpha_conversation_memory_archived_by_proposal_fkey
            FOREIGN KEY (archived_by_proposal_id)
            REFERENCES public.alpha_memory_consolidation_proposals(id)
            ON DELETE RESTRICT;
    END IF;
END
$constraints$;

CREATE INDEX IF NOT EXISTS idx_alpha_conversation_memory_consolidation_hold
    ON public.alpha_conversation_memory(consolidation_hold_proposal_id)
    WHERE consolidation_hold = true;
CREATE INDEX IF NOT EXISTS idx_alpha_conversation_memory_archived
    ON public.alpha_conversation_memory(archived_by_proposal_id, archived_at)
    WHERE archived_at IS NOT NULL;

CREATE OR REPLACE FUNCTION public.revert_consolidation(p_proposal_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
    v_proposal public.alpha_memory_consolidation_proposals%ROWTYPE;
    v_ledger public.alpha_memory_consolidation_execution_ledger%ROWTYPE;
    v_source_id uuid;
    v_restored integer := 0;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    SELECT *
      INTO v_proposal
      FROM public.alpha_memory_consolidation_proposals
     WHERE id = p_proposal_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'CONSOLIDATION_PROPOSAL_NOT_FOUND proposal_id=%', p_proposal_id
            USING ERRCODE = 'P0020';
    END IF;

    SELECT *
      INTO v_ledger
      FROM public.alpha_memory_consolidation_execution_ledger
     WHERE proposal_id = p_proposal_id
       AND operation = 'archive_working'
     ORDER BY executed_at DESC
     LIMIT 1
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'CONSOLIDATION_LEDGER_NOT_FOUND proposal_id=%', p_proposal_id
            USING ERRCODE = 'P0021';
    END IF;

    IF v_ledger.status = 'reverted' THEN
        RETURN jsonb_build_object(
            'status', 'already_reverted',
            'proposal_id', p_proposal_id,
            'ledger_id', v_ledger.id
        );
    END IF;

    IF array_length(v_ledger.source_memory_ids, 1) <> 1 THEN
        RAISE EXCEPTION 'CONSOLIDATION_REVERT_SOURCE_CARDINALITY proposal_id=% source_count=%',
            p_proposal_id,
            COALESCE(array_length(v_ledger.source_memory_ids, 1), 0)
            USING ERRCODE = 'P0022';
    END IF;

    v_source_id := v_ledger.source_memory_ids[1]::uuid;

    UPDATE public.alpha_conversation_memory
       SET tier = 'working',
           archived_at = NULL,
           archived_by_proposal_id = NULL,
           consolidation_hold = false,
           consolidation_hold_proposal_id = NULL
     WHERE id = v_source_id
       AND archived_by_proposal_id = p_proposal_id;

    GET DIAGNOSTICS v_restored = ROW_COUNT;

    IF v_restored <> 1 THEN
        RAISE EXCEPTION 'CONSOLIDATION_REVERT_RESTORE_FAILED proposal_id=% restored_rows=%',
            p_proposal_id,
            v_restored
            USING ERRCODE = 'P0029';
    END IF;

    UPDATE public.alpha_memory_consolidation_execution_ledger
       SET status = 'reverted',
           reverted_at = NOW()
     WHERE id = v_ledger.id;

    UPDATE public.alpha_memory_consolidation_proposals
       SET status = 'reverted',
           updated_at = NOW()
     WHERE id = p_proposal_id;

    RETURN jsonb_build_object(
        'status', 'reverted',
        'proposal_id', p_proposal_id,
        'ledger_id', v_ledger.id,
        'source_memory_id', v_source_id,
        'restored_rows', v_restored
    );
END;
$function$;

CREATE OR REPLACE FUNCTION public.execute_memory_consolidation_archive(
    p_proposal_id uuid,
    p_approval_queue_id uuid,
    p_executed_by text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
    v_proposal public.alpha_memory_consolidation_proposals%ROWTYPE;
    v_approval public.alpha_approval_queue%ROWTYPE;
    v_source public.alpha_conversation_memory%ROWTYPE;
    v_source_id uuid;
    v_ledger_id uuid;
    v_postcheck_failed boolean := false;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    SELECT *
      INTO v_proposal
      FROM public.alpha_memory_consolidation_proposals
     WHERE id = p_proposal_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'CONSOLIDATION_PROPOSAL_NOT_FOUND proposal_id=%', p_proposal_id
            USING ERRCODE = 'P0020';
    END IF;

    IF v_proposal.status = 'executed' THEN
        RAISE EXCEPTION 'CONSOLIDATION_PROPOSAL_ALREADY_EXECUTED proposal_id=%', p_proposal_id
            USING ERRCODE = 'P0023';
    END IF;

    IF v_proposal.status IN ('reverted', 'rejected', 'stale') THEN
        RAISE EXCEPTION 'CONSOLIDATION_PROPOSAL_TERMINAL proposal_id=% status=%',
            p_proposal_id,
            v_proposal.status
            USING ERRCODE = 'P0024';
    END IF;

    IF v_proposal.candidate_action <> 'review_for_working_decay'
       OR v_proposal.proposed_action <> 'archive_working'
       OR v_proposal.executable IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'CONSOLIDATION_PROPOSAL_NOT_ARCHIVE proposal_id=% action=%',
            p_proposal_id,
            v_proposal.proposed_action
            USING ERRCODE = 'P0025';
    END IF;

    IF v_proposal.approval_queue_id IS DISTINCT FROM p_approval_queue_id THEN
        RAISE EXCEPTION 'CONSOLIDATION_APPROVAL_TOKEN_MISMATCH proposal_id=%',
            p_proposal_id
            USING ERRCODE = 'P0026';
    END IF;

    SELECT *
      INTO v_approval
      FROM public.alpha_approval_queue
     WHERE id = p_approval_queue_id
     FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'CONSOLIDATION_APPROVAL_NOT_FOUND proposal_id=% queue_id=%',
            p_proposal_id,
            p_approval_queue_id
            USING ERRCODE = 'P0027';
    END IF;

    IF v_approval.status <> 'approved'
       OR v_approval.parameters_hash <> v_proposal.parameters_hash
       OR v_approval.risk_tier <> 'T5'
       OR NOT ('memory_consolidation_reviewed_write' = ANY(v_approval.action_class))
       OR v_approval.expires_at IS NULL
       OR v_approval.expires_at <= NOW() THEN
        RAISE EXCEPTION 'CONSOLIDATION_APPROVAL_NOT_USABLE proposal_id=% queue_id=% status=%',
            p_proposal_id,
            p_approval_queue_id,
            v_approval.status
            USING ERRCODE = 'P0028';
    END IF;

    IF array_length(v_proposal.source_memory_ids, 1) <> 1 THEN
        UPDATE public.alpha_memory_consolidation_proposals
           SET status = 'stale',
               updated_at = NOW()
         WHERE id = p_proposal_id;

        PERFORM public.record_buddy_event(
            v_proposal.user_id::text,
            'system',
            'Memory consolidation proposal stale',
            'Archive proposal source cardinality drifted. Re-run proposal generation.',
            2,
            'memory_consolidation',
            jsonb_build_object('proposal_id', p_proposal_id, 'reason', 'source_cardinality')
        );

        RETURN jsonb_build_object(
            'status', 'stale',
            'proposal_id', p_proposal_id,
            'reason', 'source_cardinality'
        );
    END IF;

    v_source_id := v_proposal.source_memory_ids[1]::uuid;

    SELECT *
      INTO v_source
      FROM public.alpha_conversation_memory
     WHERE id = v_source_id
     FOR UPDATE;

    IF NOT FOUND THEN
        UPDATE public.alpha_memory_consolidation_proposals
           SET status = 'stale',
               updated_at = NOW()
         WHERE id = p_proposal_id;

        PERFORM public.record_buddy_event(
            v_proposal.user_id::text,
            'system',
            'Memory consolidation proposal stale',
            'Archive proposal source no longer exists. Re-run proposal generation.',
            2,
            'memory_consolidation',
            jsonb_build_object('proposal_id', p_proposal_id, 'reason', 'candidate_missing')
        );

        RETURN jsonb_build_object(
            'status', 'stale',
            'proposal_id', p_proposal_id,
            'reason', 'candidate_missing'
        );
    END IF;

    IF v_source.user_id <> v_proposal.user_id::text
       OR v_source.tier <> 'working'
       OR v_source.persistent IS DISTINCT FROM false
       OR v_source.archived_at IS NOT NULL
       OR v_source.created_at IS NULL
       OR v_source.created_at >= NOW() - INTERVAL '20 hours' THEN
        UPDATE public.alpha_memory_consolidation_proposals
           SET status = 'stale',
               updated_at = NOW()
         WHERE id = p_proposal_id;

        PERFORM public.record_buddy_event(
            v_proposal.user_id::text,
            'system',
            'Memory consolidation proposal stale',
            'Archive proposal source changed before execution. Re-run proposal generation.',
            2,
            'memory_consolidation',
            jsonb_build_object('proposal_id', p_proposal_id, 'reason', 'candidate_drift')
        );

        RETURN jsonb_build_object(
            'status', 'stale',
            'proposal_id', p_proposal_id,
            'reason', 'candidate_drift'
        );
    END IF;

    UPDATE public.alpha_conversation_memory
       SET tier = 'archived',
           archived_at = NOW(),
           archived_by_proposal_id = p_proposal_id,
           consolidation_hold = false,
           consolidation_hold_proposal_id = NULL
     WHERE id = v_source_id;

    INSERT INTO public.alpha_memory_consolidation_execution_ledger (
        proposal_id,
        approval_queue_id,
        operation,
        source_candidate_type,
        source_memory_ids,
        destination_memory_ids,
        evidence,
        decision,
        undo_path,
        status,
        executed_by
    )
    VALUES (
        p_proposal_id,
        p_approval_queue_id,
        'archive_working',
        v_proposal.candidate_action,
        ARRAY[v_source_id::text],
        ARRAY[v_source_id::text],
        jsonb_build_object(
            'proposal', v_proposal.evidence,
            'source_snapshot',
            jsonb_build_object(
                'id', v_source.id,
                'user_id', v_source.user_id,
                'tier', v_source.tier,
                'persistent', v_source.persistent,
                'created_at', v_source.created_at,
                'importance_score', v_source.importance_score,
                'access_count', v_source.access_count,
                'summary', v_source.summary
            )
        ),
        jsonb_build_object(
            'approval_queue_id', v_approval.id,
            'decided_by', v_approval.decided_by,
            'decided_at', v_approval.decided_at,
            'executed_by', p_executed_by
        ),
        jsonb_build_object(
            'operation', 'restore_working_memory',
            'source_memory_id', v_source_id,
            'restore_tier', 'working'
        ),
        'executed',
        p_executed_by
    )
    RETURNING id INTO v_ledger_id;

    UPDATE public.alpha_memory_consolidation_proposals
       SET status = 'executed',
           updated_at = NOW()
     WHERE id = p_proposal_id;

    UPDATE public.alpha_approval_queue
       SET status = 'executed',
           executed_at = NOW()
     WHERE id = p_approval_queue_id;

    SELECT EXISTS (
        SELECT 1
          FROM public.alpha_conversation_memory
         WHERE id = v_source_id
           AND archived_by_proposal_id = p_proposal_id
           AND user_id <> v_proposal.user_id::text
    )
      INTO v_postcheck_failed;

    IF v_postcheck_failed THEN
        PERFORM public.revert_consolidation(p_proposal_id);
        PERFORM public.record_buddy_event(
            'system',
            'alert',
            'Memory consolidation child boundary post-check failed',
            'Archive execution was auto-reverted because the post-execution boundary check failed.',
            3,
            'memory_consolidation',
            jsonb_build_object('proposal_id', p_proposal_id, 'ledger_id', v_ledger_id)
        );

        RETURN jsonb_build_object(
            'status', 'postcheck_failed_reverted',
            'proposal_id', p_proposal_id,
            'ledger_id', v_ledger_id
        );
    END IF;

    RETURN jsonb_build_object(
        'status', 'executed',
        'proposal_id', p_proposal_id,
        'ledger_id', v_ledger_id,
        'source_memory_id', v_source_id,
        'operation', 'archive_working'
    );
END;
$function$;

CREATE OR REPLACE FUNCTION public.mark_memory_consolidation_archive_hold(
    p_proposal_id uuid
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
    v_proposal public.alpha_memory_consolidation_proposals%ROWTYPE;
    v_source_id uuid;
    v_count integer := 0;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    SELECT *
      INTO v_proposal
      FROM public.alpha_memory_consolidation_proposals
     WHERE id = p_proposal_id;

    IF NOT FOUND
       OR v_proposal.candidate_action <> 'review_for_working_decay'
       OR v_proposal.proposed_action <> 'archive_working'
       OR v_proposal.status NOT IN ('pending_review', 'queued', 'approved') THEN
        RETURN 0;
    END IF;

    IF array_length(v_proposal.source_memory_ids, 1) <> 1 THEN
        RETURN 0;
    END IF;

    v_source_id := v_proposal.source_memory_ids[1]::uuid;

    UPDATE public.alpha_conversation_memory
       SET consolidation_hold = true,
           consolidation_hold_proposal_id = p_proposal_id
     WHERE id = v_source_id
       AND user_id = v_proposal.user_id::text
       AND tier = 'working'
       AND persistent = false
       AND archived_at IS NULL;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$function$;

CREATE OR REPLACE FUNCTION public.evict_expired_working_memory()
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
  v_count INTEGER;
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  DELETE FROM public.alpha_conversation_memory AS m
  WHERE m.tier = 'working'
    AND m.persistent = false
    AND m.created_at < now() - interval '24 hours'
    AND NOT (
        COALESCE(m.consolidation_hold, false)
        AND EXISTS (
            SELECT 1
              FROM public.alpha_memory_consolidation_proposals AS p
             WHERE p.id = m.consolidation_hold_proposal_id
               AND p.status IN ('pending_review', 'queued', 'approved')
        )
    );

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
EXCEPTION
  WHEN sqlstate '23503' OR sqlstate '23505' OR sqlstate '23514' OR sqlstate '23P01' THEN
    RAISE;
  WHEN sqlstate '40001' OR sqlstate '40P01' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'evict_expired_working_memory failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN 0;
END;
$function$;

CREATE OR REPLACE FUNCTION public.get_buddy_promotion_candidates(p_user_id text)
 RETURNS TABLE(id uuid, summary text)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  RETURN QUERY
  SELECT m.id, m.summary
  FROM public.alpha_conversation_memory AS m
  WHERE m.user_id = p_user_id
    AND m.tier = 'working'
    AND m.created_at < now() - interval '20 hours'
    AND NOT (
        COALESCE(m.consolidation_hold, false)
        AND EXISTS (
            SELECT 1
              FROM public.alpha_memory_consolidation_proposals AS p
             WHERE p.id = m.consolidation_hold_proposal_id
               AND p.status IN ('pending_review', 'queued', 'approved')
        )
    )
  LIMIT 5;
EXCEPTION
  WHEN integrity_constraint_violation THEN
    RAISE;
  WHEN transaction_rollback THEN
    RAISE;
  WHEN SQLSTATE '57014' OR SQLSTATE '55P03' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'get_buddy_promotion_candidates failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN;
END;
$function$;

REVOKE ALL ON FUNCTION public.execute_memory_consolidation_archive(uuid, uuid, text)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION public.revert_consolidation(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.mark_memory_consolidation_archive_hold(uuid)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION public.evict_expired_working_memory() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.get_buddy_promotion_candidates(text) FROM PUBLIC;

DO $owner$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvisbrain') THEN
        EXECUTE
            'ALTER FUNCTION public.execute_memory_consolidation_archive'
            || '(uuid, uuid, text) OWNER TO jarvisbrain';
        EXECUTE
            'ALTER FUNCTION public.revert_consolidation(uuid) OWNER TO jarvisbrain';
        EXECUTE
            'ALTER FUNCTION public.mark_memory_consolidation_archive_hold'
            || '(uuid) OWNER TO jarvisbrain';
        EXECUTE
            'ALTER FUNCTION public.evict_expired_working_memory() OWNER TO jarvisbrain';
        EXECUTE
            'ALTER FUNCTION public.get_buddy_promotion_candidates(text) OWNER TO jarvisbrain';
    END IF;
END
$owner$;

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT EXECUTE ON FUNCTION public.execute_memory_consolidation_archive(
            uuid, uuid, text
        ) TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.revert_consolidation(uuid)
            TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.mark_memory_consolidation_archive_hold(uuid)
            TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT EXECUTE ON FUNCTION public.execute_memory_consolidation_archive(
            uuid, uuid, text
        ) TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.revert_consolidation(uuid)
            TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.mark_memory_consolidation_archive_hold(uuid)
            TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.evict_expired_working_memory()
            TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.get_buddy_promotion_candidates(text)
            TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON FUNCTION public.execute_memory_consolidation_archive(uuid, uuid, text) IS
    'ADR-0026 PR-2 archive_working executor. Validates proposal-bound T5 approval token, candidate freshness, writes archive + ledger atomically, then consumes approval.';
COMMENT ON FUNCTION public.revert_consolidation(uuid) IS
    'ADR-0026 PR-2 archive revert. Restores archived working memory from the mandatory ledger.';
COMMENT ON FUNCTION public.mark_memory_consolidation_archive_hold(uuid) IS
    'ADR-0026 PR-2 Buddy hold marker for pending/approved archive proposals.';
COMMENT ON COLUMN public.alpha_conversation_memory.consolidation_hold IS
    'Buddy eviction hold while an archive proposal is pending or approved-but-unexecuted.';
COMMENT ON COLUMN public.alpha_conversation_memory.archived_at IS
    'Soft archive timestamp for restorable ADR-0026 working-memory archive.';

DO $postcheck$
DECLARE
    v_definition text;
BEGIN
    SELECT pg_get_functiondef(p.oid)
      INTO v_definition
      FROM pg_proc p
     WHERE p.proname = 'execute_memory_consolidation_archive'
       AND p.pronamespace = 'public'::regnamespace;

    IF v_definition IS NULL
       OR v_definition NOT LIKE '%v_approval.status <> ''approved''%'
       OR v_definition NOT LIKE '%INSERT INTO public.alpha_memory_consolidation_execution_ledger%'
       OR v_definition NOT LIKE '%v_source.created_at IS NULL%'
       OR v_definition NOT LIKE '%v_source.created_at >= NOW() - INTERVAL ''20 hours''%' THEN
        RAISE EXCEPTION 'ADR-0026 archive executor postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;
