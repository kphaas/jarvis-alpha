-- Grant contained owner role execute on semantic memory review SECDEF functions.
-- The legacy save_semantic_memory wrapper is owned by jarvis_alpha_owner and
-- delegates to save_semantic_memory_with_provenance, so it needs an explicit
-- grant after PUBLIC execute is revoked.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260618155500);

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_owner') THEN
        GRANT EXECUTE ON FUNCTION public.save_semantic_memory_with_provenance(UUID, TEXT, TEXT, JSONB, TEXT, TEXT)
            TO jarvis_alpha_owner;
        GRANT EXECUTE ON FUNCTION public.review_semantic_memory(UUID, UUID, TEXT, TEXT, TEXT)
            TO jarvis_alpha_owner;
    END IF;
END
$grants$;

DO $postcheck$
DECLARE
    v_missing INTEGER;
    v_public_execute INTEGER;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_owner') THEN
        SELECT COUNT(*)::INTEGER
          INTO v_missing
          FROM pg_proc p
         WHERE p.proname IN (
                'save_semantic_memory_with_provenance',
                'review_semantic_memory'
            )
           AND NOT has_function_privilege('jarvis_alpha_owner', p.oid, 'EXECUTE');

        IF COALESCE(v_missing, 0) <> 0 THEN
            RAISE EXCEPTION 'semantic memory SECDEF owner grant postcheck failed';
        END IF;
    END IF;

    SELECT COUNT(*)::INTEGER
      INTO v_public_execute
      FROM pg_proc p
     WHERE p.proname IN (
            'save_semantic_memory_with_provenance',
            'review_semantic_memory'
        )
       AND EXISTS (
            SELECT 1
              FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) acl
             WHERE acl.grantee = 0
               AND acl.privilege_type = 'EXECUTE'
        );

    IF COALESCE(v_public_execute, 0) <> 0 THEN
        RAISE EXCEPTION 'semantic memory SECDEF owner grant restored PUBLIC execute';
    END IF;
END
$postcheck$;

COMMIT;
