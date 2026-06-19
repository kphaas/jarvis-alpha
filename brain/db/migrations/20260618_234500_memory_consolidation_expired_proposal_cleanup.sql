-- Purpose: expire Dream memory consolidation proposals whose approval token is
-- no longer executable, and release archive holds tied to those proposals.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260618234500);

CREATE OR REPLACE FUNCTION public.expire_stale_memory_consolidation_proposals()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
    v_staled integer := 0;
    v_released_holds integer := 0;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    WITH stale AS (
        SELECT p.id, p.proposed_action
          FROM public.alpha_memory_consolidation_proposals p
          JOIN public.alpha_approval_queue q
            ON q.id = p.approval_queue_id
         WHERE p.executable
           AND p.status IN ('pending_review', 'queued', 'approved')
           AND (
                q.status IN ('expired', 'denied', 'executed')
                OR q.expires_at IS NULL
                OR q.expires_at <= NOW()
           )
    ),
    updated AS (
        UPDATE public.alpha_memory_consolidation_proposals p
           SET status = 'stale',
               updated_at = NOW()
          FROM stale
         WHERE p.id = stale.id
        RETURNING p.id, stale.proposed_action
    ),
    released_holds AS (
        UPDATE public.alpha_conversation_memory m
           SET consolidation_hold = false,
               consolidation_hold_proposal_id = NULL
         WHERE m.consolidation_hold = true
           AND m.consolidation_hold_proposal_id IN (
                SELECT id
                  FROM updated
                 WHERE proposed_action = 'archive_working'
           )
        RETURNING 1
    )
    SELECT
        (SELECT count(*)::integer FROM updated),
        (SELECT count(*)::integer FROM released_holds)
      INTO v_staled, v_released_holds;

    RETURN jsonb_build_object(
        'status', 'ok',
        'staled_proposals', COALESCE(v_staled, 0),
        'released_holds', COALESCE(v_released_holds, 0)
    );
END;
$function$;

REVOKE ALL ON FUNCTION public.expire_stale_memory_consolidation_proposals()
    FROM PUBLIC;

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT EXECUTE ON FUNCTION public.expire_stale_memory_consolidation_proposals()
            TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT EXECUTE ON FUNCTION public.expire_stale_memory_consolidation_proposals()
            TO jarvis_alpha_writer;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvisbrain') THEN
        GRANT EXECUTE ON FUNCTION public.expire_stale_memory_consolidation_proposals()
            TO jarvisbrain;
    END IF;
END
$grants$;

COMMENT ON FUNCTION public.expire_stale_memory_consolidation_proposals() IS
    'Marks active memory consolidation proposals stale when their approval token is expired/denied/executed or past expires_at, and releases archive holds.';

SELECT public.expire_stale_memory_consolidation_proposals();

DO $postcheck$
DECLARE
    v_definition text;
BEGIN
    SELECT pg_get_functiondef(p.oid)
      INTO v_definition
      FROM pg_proc p
     WHERE p.proname = 'expire_stale_memory_consolidation_proposals'
       AND p.pronamespace = 'public'::regnamespace;

    IF v_definition IS NULL
       OR v_definition NOT LIKE '%PERFORM set_config(''rls.role'', ''platform_admin'', true)%'
       OR v_definition NOT LIKE '%q.expires_at <= NOW()%'
       OR v_definition NOT LIKE '%consolidation_hold = false%'
       OR v_definition NOT LIKE '%status = ''stale''%' THEN
        RAISE EXCEPTION 'memory consolidation stale proposal cleanup postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;
