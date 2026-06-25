-- Revoke implicit PUBLIC execute on the temporal graph trigger helper.
--
-- public.enforce_memory_graph_valid_window() is an internal trigger function,
-- not an app-facing RPC. Leaving PostgreSQL's default PUBLIC EXECUTE grant on
-- it widens the callable surface unnecessarily.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260623205000);

DO $function_exists$
BEGIN
    IF to_regprocedure('public.enforce_memory_graph_valid_window()') IS NULL THEN
        RAISE EXCEPTION 'missing function public.enforce_memory_graph_valid_window()';
    END IF;
END
$function_exists$;

REVOKE EXECUTE ON FUNCTION public.enforce_memory_graph_valid_window()
    FROM PUBLIC;

DO $postcheck$
DECLARE
    v_public_execute INTEGER;
BEGIN
    SELECT COUNT(*)::INTEGER
      INTO v_public_execute
      FROM pg_proc p
     WHERE p.oid = to_regprocedure('public.enforce_memory_graph_valid_window()')
       AND EXISTS (
            SELECT 1
              FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) acl
             WHERE acl.grantee = 0
               AND acl.privilege_type = 'EXECUTE'
        );

    IF COALESCE(v_public_execute, 0) <> 0 THEN
        RAISE EXCEPTION 'memory graph valid-window helper public EXECUTE revoke postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;
