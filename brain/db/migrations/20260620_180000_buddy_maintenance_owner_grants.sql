-- Grant the Buddy maintenance owner role execute on every delegated function.
--
-- run_buddy_memory_maintenance is SECURITY DEFINER and is owned by
-- jarvis_alpha_owner in production. Its inner functions are owned separately,
-- so the wrapper owner must have explicit EXECUTE grants or maintenance emits
-- permission-denied errors as high-priority Buddy noise.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260620180000);

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_owner') THEN
        GRANT EXECUTE ON FUNCTION public.evict_expired_working_memory()
            TO jarvis_alpha_owner;
        GRANT EXECUTE ON FUNCTION public.archive_old_low_priority_buddy_events(
            INTEGER,
            INTEGER,
            INTEGER
        ) TO jarvis_alpha_owner;
        GRANT EXECUTE ON FUNCTION public.evict_episodic_memory_older_than(
            TEXT,
            INTEGER
        ) TO jarvis_alpha_owner;
        GRANT EXECUTE ON FUNCTION public.cap_episodic_memory(TEXT, INTEGER)
            TO jarvis_alpha_owner;
        GRANT EXECUTE ON FUNCTION public.cap_semantic_memory(TEXT, INTEGER)
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
        WITH expected(identity) AS (
            VALUES
                ('public.evict_expired_working_memory()'),
                (
                    'public.archive_old_low_priority_buddy_events(integer,integer,integer)'
                ),
                ('public.evict_episodic_memory_older_than(text,integer)'),
                ('public.cap_episodic_memory(text,integer)'),
                ('public.cap_semantic_memory(text,integer)')
        ),
        resolved AS (
            SELECT identity, to_regprocedure(identity) AS oid
              FROM expected
        )
        SELECT COUNT(*)::INTEGER
          INTO v_missing
          FROM resolved
         WHERE oid IS NULL
            OR NOT has_function_privilege('jarvis_alpha_owner', oid, 'EXECUTE');

        IF COALESCE(v_missing, 0) <> 0 THEN
            RAISE EXCEPTION 'Buddy maintenance owner grant postcheck failed';
        END IF;
    END IF;

    WITH expected(identity) AS (
        VALUES
            ('public.evict_expired_working_memory()'),
            (
                'public.archive_old_low_priority_buddy_events(integer,integer,integer)'
            ),
            ('public.evict_episodic_memory_older_than(text,integer)'),
            ('public.cap_episodic_memory(text,integer)'),
            ('public.cap_semantic_memory(text,integer)')
    ),
    resolved AS (
        SELECT to_regprocedure(identity) AS oid
          FROM expected
    )
    SELECT COUNT(*)::INTEGER
      INTO v_public_execute
      FROM pg_proc p
      JOIN resolved r ON r.oid = p.oid
     WHERE EXISTS (
            SELECT 1
              FROM aclexplode(COALESCE(p.proacl, acldefault('f', p.proowner))) acl
             WHERE acl.grantee = 0
               AND acl.privilege_type = 'EXECUTE'
        );

    IF COALESCE(v_public_execute, 0) <> 0 THEN
        RAISE EXCEPTION 'Buddy maintenance owner grant restored PUBLIC execute';
    END IF;
END
$postcheck$;

COMMIT;
