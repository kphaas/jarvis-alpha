-- Purpose: expire temporal graph proposals whose approval token is no longer
-- executable, so observability drift cannot build up after T5 approvals expire.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260622153000);

CREATE OR REPLACE FUNCTION public.expire_stale_memory_graph_proposals()
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
    v_rejected integer := 0;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    WITH expired AS (
        SELECT p.id
          FROM public.alpha_memory_graph_proposals p
          LEFT JOIN public.alpha_approval_queue q
            ON q.id = p.approval_queue_id
         WHERE p.status IN ('queued', 'approved')
           AND (
                p.approval_queue_id IS NULL
                OR q.id IS NULL
                OR q.status IN ('expired', 'denied', 'executed')
                OR q.status NOT IN ('pending', 'approved')
                OR q.expires_at IS NULL
                OR q.expires_at <= NOW()
           )
    ),
    updated AS (
        UPDATE public.alpha_memory_graph_proposals p
           SET status = 'rejected',
               reason = CASE
                   WHEN NULLIF(btrim(COALESCE(p.reason, '')), '') IS NULL THEN
                       'Rejected automatically: approval token expired or is no longer executable.'
                   WHEN p.reason LIKE '%approval token expired or is no longer executable%' THEN
                       p.reason
                   ELSE
                       p.reason || E'\nRejected automatically: approval token expired or is no longer executable.'
               END,
               updated_at = NOW()
          FROM expired
         WHERE p.id = expired.id
        RETURNING 1
    )
    SELECT count(*)::integer
      INTO v_rejected
      FROM updated;

    RETURN jsonb_build_object(
        'status', 'ok',
        'rejected_proposals', COALESCE(v_rejected, 0)
    );
END;
$function$;

REVOKE ALL ON FUNCTION public.expire_stale_memory_graph_proposals()
    FROM PUBLIC;

DO $owner$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvisbrain') THEN
        EXECUTE 'ALTER FUNCTION public.expire_stale_memory_graph_proposals() OWNER TO jarvisbrain';
    END IF;
END
$owner$;

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT EXECUTE ON FUNCTION public.expire_stale_memory_graph_proposals()
            TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT EXECUTE ON FUNCTION public.expire_stale_memory_graph_proposals()
            TO jarvis_alpha_writer;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvisbrain') THEN
        GRANT EXECUTE ON FUNCTION public.expire_stale_memory_graph_proposals()
            TO jarvisbrain;
    END IF;
END
$grants$;

COMMENT ON FUNCTION public.expire_stale_memory_graph_proposals() IS
    'Rejects queued or approved temporal graph proposals whose approval token is missing, expired, denied, executed, or otherwise no longer executable.';

SELECT public.expire_stale_memory_graph_proposals();

DO $postcheck$
DECLARE
    v_definition text;
BEGIN
    SELECT pg_get_functiondef(p.oid)
      INTO v_definition
      FROM pg_proc p
     WHERE p.proname = 'expire_stale_memory_graph_proposals'
       AND p.pronamespace = 'public'::regnamespace;

    IF v_definition IS NULL
       OR v_definition NOT LIKE '%PERFORM set_config(''rls.role'', ''platform_admin'', true)%'
       OR v_definition NOT LIKE '%q.expires_at <= NOW()%'
       OR v_definition NOT LIKE '%status = ''rejected''%'
       OR v_definition NOT LIKE '%approval token expired or is no longer executable%' THEN
        RAISE EXCEPTION 'memory graph expired proposal cleanup postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;
