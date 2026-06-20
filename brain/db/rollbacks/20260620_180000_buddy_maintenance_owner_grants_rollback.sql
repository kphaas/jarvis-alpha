-- Rollback for 20260620_180000_buddy_maintenance_owner_grants.sql.
--
-- Removes only the explicit EXECUTE grants added for jarvis_alpha_owner.
-- This rollback can restore the Buddy maintenance permission-denied failure
-- mode, so use it only when rolling back the corresponding forward migration.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260620180000);

DO $revoke$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_owner') THEN
        REVOKE EXECUTE ON FUNCTION public.evict_expired_working_memory()
            FROM jarvis_alpha_owner;
        REVOKE EXECUTE ON FUNCTION public.archive_old_low_priority_buddy_events(
            INTEGER,
            INTEGER,
            INTEGER
        ) FROM jarvis_alpha_owner;
        REVOKE EXECUTE ON FUNCTION public.evict_episodic_memory_older_than(
            TEXT,
            INTEGER
        ) FROM jarvis_alpha_owner;
        REVOKE EXECUTE ON FUNCTION public.cap_episodic_memory(TEXT, INTEGER)
            FROM jarvis_alpha_owner;
        REVOKE EXECUTE ON FUNCTION public.cap_semantic_memory(TEXT, INTEGER)
            FROM jarvis_alpha_owner;
    END IF;
END
$revoke$;

DO $postcheck$
DECLARE
    v_owner_oid OID;
    v_explicit_grants INTEGER;
BEGIN
    SELECT oid
      INTO v_owner_oid
      FROM pg_roles
     WHERE rolname = 'jarvis_alpha_owner';

    IF v_owner_oid IS NULL THEN
        RETURN;
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
      INTO v_explicit_grants
      FROM pg_proc p
      JOIN resolved r ON r.oid = p.oid
     WHERE EXISTS (
            SELECT 1
              FROM aclexplode(COALESCE(p.proacl, ARRAY[]::aclitem[])) acl
             WHERE acl.grantee = v_owner_oid
               AND acl.privilege_type = 'EXECUTE'
        );

    IF COALESCE(v_explicit_grants, 0) <> 0 THEN
        RAISE EXCEPTION
            'Buddy maintenance owner grant rollback left explicit EXECUTE grants';
    END IF;
END
$postcheck$;

COMMIT;
