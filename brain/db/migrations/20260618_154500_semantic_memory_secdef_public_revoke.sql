-- Revoke implicit PUBLIC execute on semantic memory review SECDEF functions.
-- The provenance migration grants app/writer roles explicitly; this migration
-- closes the default function EXECUTE grant left on newly-created functions.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260618154500);

REVOKE EXECUTE ON FUNCTION public.save_semantic_memory_with_provenance(
    UUID,
    TEXT,
    TEXT,
    JSONB,
    TEXT,
    TEXT
) FROM PUBLIC;

REVOKE EXECUTE ON FUNCTION public.review_semantic_memory(
    UUID,
    UUID,
    TEXT,
    TEXT,
    TEXT
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.save_semantic_memory_with_provenance(
    UUID,
    TEXT,
    TEXT,
    JSONB,
    TEXT,
    TEXT
) TO jarvisbrain;

GRANT EXECUTE ON FUNCTION public.review_semantic_memory(
    UUID,
    UUID,
    TEXT,
    TEXT,
    TEXT
) TO jarvisbrain;

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT EXECUTE ON FUNCTION public.save_semantic_memory_with_provenance(UUID, TEXT, TEXT, JSONB, TEXT, TEXT)
            TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.review_semantic_memory(UUID, UUID, TEXT, TEXT, TEXT)
            TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT EXECUTE ON FUNCTION public.save_semantic_memory_with_provenance(UUID, TEXT, TEXT, JSONB, TEXT, TEXT)
            TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.review_semantic_memory(UUID, UUID, TEXT, TEXT, TEXT)
            TO jarvis_alpha_writer;
    END IF;
END
$grants$;

DO $postcheck$
DECLARE
    v_public_execute INTEGER;
BEGIN
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
        RAISE EXCEPTION 'semantic memory SECDEF public revoke postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;
