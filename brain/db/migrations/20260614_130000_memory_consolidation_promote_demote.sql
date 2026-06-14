-- ADR-0026 PR-3: promote_episodic_to_semantic executor and demotion revert.
-- Scope: reviewed semantic promotion only. No duplicate-merge executor.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260614130000);

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
    v_destination_id uuid;
    v_restored integer := 0;
    v_deleted integer := 0;
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

    IF v_ledger.operation = 'archive_working' THEN
        IF COALESCE(array_length(v_ledger.source_memory_ids, 1), 0) <> 1 THEN
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

    ELSIF v_ledger.operation = 'promote_episodic_to_semantic' THEN
        IF COALESCE(array_length(v_ledger.destination_memory_ids, 1), 0) <> 1 THEN
            RAISE EXCEPTION 'CONSOLIDATION_REVERT_DESTINATION_CARDINALITY proposal_id=% destination_count=%',
                p_proposal_id,
                COALESCE(array_length(v_ledger.destination_memory_ids, 1), 0)
                USING ERRCODE = 'P0030';
        END IF;

        v_destination_id := v_ledger.destination_memory_ids[1]::uuid;

        DELETE FROM public.alpha_semantic_memory
         WHERE id = v_destination_id
           AND user_id = v_proposal.user_id;

        GET DIAGNOSTICS v_deleted = ROW_COUNT;

        IF v_deleted <> 1 THEN
            RAISE EXCEPTION 'CONSOLIDATION_REVERT_DEMOTE_FAILED proposal_id=% deleted_rows=%',
                p_proposal_id,
                v_deleted
                USING ERRCODE = 'P0031';
        END IF;
    ELSE
        RAISE EXCEPTION 'CONSOLIDATION_REVERT_UNSUPPORTED_OPERATION proposal_id=% operation=%',
            p_proposal_id,
            v_ledger.operation
            USING ERRCODE = 'P0032';
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
        'operation', v_ledger.operation,
        'restored_rows', v_restored,
        'deleted_rows', v_deleted
    );
END;
$function$;

CREATE OR REPLACE FUNCTION public.execute_memory_consolidation_promotion(
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
    v_semantic_id uuid;
    v_ledger_id uuid;
    v_fact text;
    v_category text;
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

    IF v_proposal.candidate_action <> 'review_for_semantic_promotion'
       OR v_proposal.proposed_action <> 'promote_episodic_to_semantic'
       OR v_proposal.executable IS DISTINCT FROM true THEN
        RAISE EXCEPTION 'CONSOLIDATION_PROPOSAL_NOT_PROMOTION proposal_id=% action=%',
            p_proposal_id,
            v_proposal.proposed_action
            USING ERRCODE = 'P0033';
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

    IF COALESCE(array_length(v_proposal.source_memory_ids, 1), 0) <> 1 THEN
        UPDATE public.alpha_memory_consolidation_proposals
           SET status = 'stale',
               updated_at = NOW()
         WHERE id = p_proposal_id;

        PERFORM public.record_buddy_event(
            v_proposal.user_id::text,
            'system',
            'Memory consolidation proposal stale',
            'Promotion proposal source cardinality drifted. Re-run proposal generation.',
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
            'Promotion proposal source no longer exists. Re-run proposal generation.',
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
       OR v_source.tier NOT IN ('working', 'episodic')
       OR v_source.archived_at IS NOT NULL
       OR NOT (
            COALESCE(v_source.importance_score, 0) >= 0.7
            OR COALESCE(v_source.access_count, 0) >= 3
       )
       OR EXISTS (
            SELECT 1
              FROM public.alpha_memory_consolidation_execution_ledger AS ledger
             WHERE ledger.operation = 'promote_episodic_to_semantic'
               AND ledger.status = 'executed'
               AND ledger.source_memory_ids @> ARRAY[v_source_id::text]
       ) THEN
        UPDATE public.alpha_memory_consolidation_proposals
           SET status = 'stale',
               updated_at = NOW()
         WHERE id = p_proposal_id;

        PERFORM public.record_buddy_event(
            v_proposal.user_id::text,
            'system',
            'Memory consolidation proposal stale',
            'Promotion proposal source changed before execution. Re-run proposal generation.',
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

    v_fact := NULLIF(
        btrim(
            COALESCE(
                v_proposal.evidence->>'summary',
                v_source.summary,
                v_source.content,
                ''
            )
        ),
        ''
    );

    IF v_fact IS NULL THEN
        UPDATE public.alpha_memory_consolidation_proposals
           SET status = 'stale',
               updated_at = NOW()
         WHERE id = p_proposal_id;

        PERFORM public.record_buddy_event(
            v_proposal.user_id::text,
            'system',
            'Memory consolidation proposal stale',
            'Promotion proposal has no fact text. Re-run proposal generation.',
            2,
            'memory_consolidation',
            jsonb_build_object('proposal_id', p_proposal_id, 'reason', 'empty_fact')
        );

        RETURN jsonb_build_object(
            'status', 'stale',
            'proposal_id', p_proposal_id,
            'reason', 'empty_fact'
        );
    END IF;

    v_fact := LEFT(v_fact, 500);
    v_category := CASE
        WHEN v_fact ~* '(health|medical|doctor|medicine|kidney)' THEN 'health'
        WHEN v_fact ~* '(ryleigh|sloane|child|daughter|school)' THEN 'child_profile'
        WHEN v_fact ~* '(must|never|always|guardrail|legal|approval|draft-only|no-send|risk)' THEN 'constraint'
        WHEN v_fact ~* '(spark|jarvis|alpha|memory|bluebubbles|forge|family|financial|project)' THEN 'project'
        WHEN v_fact ~* '(sweta|mother|meagan|person|relationship)' THEN 'person'
        ELSE 'preference'
    END;

    IF EXISTS (
        SELECT 1
          FROM public.alpha_semantic_memory
         WHERE user_id = v_proposal.user_id
           AND fact = v_fact
    ) THEN
        UPDATE public.alpha_memory_consolidation_proposals
           SET status = 'stale',
               updated_at = NOW()
         WHERE id = p_proposal_id;

        PERFORM public.record_buddy_event(
            v_proposal.user_id::text,
            'system',
            'Memory consolidation proposal stale',
            'Promotion proposal duplicates an existing semantic fact.',
            2,
            'memory_consolidation',
            jsonb_build_object('proposal_id', p_proposal_id, 'reason', 'duplicate_fact')
        );

        RETURN jsonb_build_object(
            'status', 'stale',
            'proposal_id', p_proposal_id,
            'reason', 'duplicate_fact'
        );
    END IF;

    INSERT INTO public.alpha_semantic_memory (
        user_id,
        fact,
        category,
        source
    )
    VALUES (
        v_proposal.user_id,
        v_fact,
        v_category,
        'dream_consolidated'
    )
    RETURNING id INTO v_semantic_id;

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
        'promote_episodic_to_semantic',
        v_proposal.candidate_action,
        ARRAY[v_source_id::text],
        ARRAY[v_semantic_id::text],
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
            ),
            'semantic_memory',
            jsonb_build_object(
                'id', v_semantic_id,
                'fact', v_fact,
                'category', v_category,
                'source', 'dream_consolidated'
            )
        ),
        jsonb_build_object(
            'approval_queue_id', v_approval.id,
            'decided_by', v_approval.decided_by,
            'decided_at', v_approval.decided_at,
            'executed_by', p_executed_by
        ),
        jsonb_build_object(
            'operation', 'delete_semantic_memory',
            'semantic_memory_id', v_semantic_id
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
          FROM public.alpha_semantic_memory
         WHERE id = v_semantic_id
           AND user_id <> v_proposal.user_id
    )
      INTO v_postcheck_failed;

    IF v_postcheck_failed THEN
        PERFORM public.revert_consolidation(p_proposal_id);
        PERFORM public.record_buddy_event(
            'system',
            'alert',
            'Memory consolidation child boundary post-check failed',
            'Promotion execution was auto-reverted because the post-execution boundary check failed.',
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
        'destination_memory_id', v_semantic_id,
        'operation', 'promote_episodic_to_semantic',
        'fact', v_fact,
        'category', v_category
    );
END;
$function$;

CREATE OR REPLACE FUNCTION public.execute_memory_consolidation_proposal(
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
    v_action text;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    SELECT proposed_action
      INTO v_action
      FROM public.alpha_memory_consolidation_proposals
     WHERE id = p_proposal_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'CONSOLIDATION_PROPOSAL_NOT_FOUND proposal_id=%', p_proposal_id
            USING ERRCODE = 'P0020';
    END IF;

    IF v_action = 'archive_working' THEN
        RETURN public.execute_memory_consolidation_archive(
            p_proposal_id,
            p_approval_queue_id,
            p_executed_by
        );
    ELSIF v_action = 'promote_episodic_to_semantic' THEN
        RETURN public.execute_memory_consolidation_promotion(
            p_proposal_id,
            p_approval_queue_id,
            p_executed_by
        );
    END IF;

    RAISE EXCEPTION 'CONSOLIDATION_PROPOSAL_UNSUPPORTED_ACTION proposal_id=% action=%',
        p_proposal_id,
        v_action
        USING ERRCODE = 'P0034';
END;
$function$;

REVOKE ALL ON FUNCTION public.execute_memory_consolidation_promotion(uuid, uuid, text)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION public.execute_memory_consolidation_proposal(uuid, uuid, text)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION public.revert_consolidation(uuid) FROM PUBLIC;

DO $owner$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvisbrain') THEN
        EXECUTE
            'ALTER FUNCTION public.execute_memory_consolidation_promotion'
            || '(uuid, uuid, text) OWNER TO jarvisbrain';
        EXECUTE
            'ALTER FUNCTION public.execute_memory_consolidation_proposal'
            || '(uuid, uuid, text) OWNER TO jarvisbrain';
        EXECUTE
            'ALTER FUNCTION public.revert_consolidation(uuid) OWNER TO jarvisbrain';
    END IF;
END
$owner$;

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT EXECUTE ON FUNCTION public.execute_memory_consolidation_promotion(
            uuid, uuid, text
        ) TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.execute_memory_consolidation_proposal(
            uuid, uuid, text
        ) TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.revert_consolidation(uuid)
            TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT EXECUTE ON FUNCTION public.execute_memory_consolidation_promotion(
            uuid, uuid, text
        ) TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.execute_memory_consolidation_proposal(
            uuid, uuid, text
        ) TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.revert_consolidation(uuid)
            TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON FUNCTION public.execute_memory_consolidation_promotion(uuid, uuid, text) IS
    'ADR-0026 PR-3 semantic promotion executor. Validates proposal-bound T5 approval token, candidate freshness, writes dream_consolidated semantic memory + ledger atomically, then consumes approval.';
COMMENT ON FUNCTION public.execute_memory_consolidation_proposal(uuid, uuid, text) IS
    'ADR-0026 reviewed-write dispatcher for archive and semantic promotion executors.';
COMMENT ON FUNCTION public.revert_consolidation(uuid) IS
    'ADR-0026 revert. Restores archived working memory or demotes dream_consolidated semantic facts via the mandatory ledger.';

DO $postcheck$
DECLARE
    v_definition text;
BEGIN
    SELECT pg_get_functiondef(p.oid)
      INTO v_definition
      FROM pg_proc p
     WHERE p.proname = 'execute_memory_consolidation_promotion'
       AND p.pronamespace = 'public'::regnamespace;

    IF v_definition IS NULL
       OR v_definition NOT LIKE '%v_approval.status <> ''approved''%'
       OR v_definition NOT LIKE '%source'', ''dream_consolidated''%'
       OR v_definition NOT LIKE '%INSERT INTO public.alpha_memory_consolidation_execution_ledger%'
       OR v_definition NOT LIKE '%ledger.source_memory_ids @> ARRAY[v_source_id::text]%' THEN
        RAISE EXCEPTION 'ADR-0026 promotion executor postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;
