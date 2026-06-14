-- Rollback: ADR-0026 promote_episodic_to_semantic executor and demotion revert.
-- Fails safely if reviewed semantic promotions are in use.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260614130000);

DO $precheck$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM public.alpha_memory_consolidation_execution_ledger
         WHERE operation = 'promote_episodic_to_semantic'
         LIMIT 1
    ) THEN
        RAISE EXCEPTION
            'Refusing rollback: promote_episodic_to_semantic ledger rows exist';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM public.alpha_semantic_memory
         WHERE source = 'dream_consolidated'
         LIMIT 1
    ) THEN
        RAISE EXCEPTION
            'Refusing rollback: dream_consolidated semantic rows exist';
    END IF;
END
$precheck$;

DROP FUNCTION IF EXISTS public.execute_memory_consolidation_proposal(uuid, uuid, text);
DROP FUNCTION IF EXISTS public.execute_memory_consolidation_promotion(uuid, uuid, text);

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

REVOKE ALL ON FUNCTION public.revert_consolidation(uuid) FROM PUBLIC;

DO $owner$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvisbrain') THEN
        EXECUTE
            'ALTER FUNCTION public.revert_consolidation(uuid) OWNER TO jarvisbrain';
    END IF;
END
$owner$;

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT EXECUTE ON FUNCTION public.revert_consolidation(uuid)
            TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT EXECUTE ON FUNCTION public.revert_consolidation(uuid)
            TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMIT;
