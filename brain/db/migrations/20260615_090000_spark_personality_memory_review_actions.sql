-- Purpose: Reviewed Spark personality memory archive action.
-- Adds a SECDEF archive function so approved memory can be removed from
-- active prompt grounding without deleting review history.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260615090000);

CREATE OR REPLACE FUNCTION public.archive_spark_personality_memory(
    p_principal_id text,
    p_memory_id uuid,
    p_archived_by text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $$
DECLARE
    v_principal text := lower(btrim(p_principal_id));
    v_archived_by text := btrim(p_archived_by);
    v_updated integer := 0;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    IF v_principal !~ '^[a-z0-9][a-z0-9_-]{0,63}$' THEN
        RETURN jsonb_build_object('archived', false, 'reason', 'invalid_principal');
    END IF;
    IF v_archived_by IS NULL OR char_length(v_archived_by) < 1 OR char_length(v_archived_by) > 128 THEN
        RETURN jsonb_build_object('archived', false, 'reason', 'invalid_archived_by');
    END IF;

    UPDATE public.alpha_personality_memory
    SET
        status = 'archived',
        archived_at = NOW(),
        updated_at = NOW()
    WHERE id = p_memory_id
      AND principal_id = v_principal
      AND status = 'active';

    GET DIAGNOSTICS v_updated = ROW_COUNT;

    RETURN jsonb_build_object(
        'archived',
        v_updated = 1,
        'personality_id',
        p_memory_id,
        'principal_id',
        v_principal,
        'archived_by',
        v_archived_by
    );
END;
$$;

REVOKE ALL ON FUNCTION public.archive_spark_personality_memory(
    text, uuid, text
) FROM PUBLIC;

DO $owner$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvisbrain') THEN
        EXECUTE
            'ALTER FUNCTION public.archive_spark_personality_memory'
            || '(text, uuid, text) OWNER TO jarvisbrain';
    END IF;
END
$owner$;

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT EXECUTE ON FUNCTION public.archive_spark_personality_memory(
            text, uuid, text
        ) TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT EXECUTE ON FUNCTION public.archive_spark_personality_memory(
            text, uuid, text
        ) TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON FUNCTION public.archive_spark_personality_memory(text, uuid, text) IS
    'Reviewed Spark personality memory archive action. Removes memory from active prompt grounding without deleting it.';

DO $postcheck$
DECLARE
    v_missing INTEGER;
BEGIN
    SELECT count(*)::INTEGER
    INTO v_missing
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.proname = 'archive_spark_personality_memory'
      AND NOT p.prosecdef;

    IF COALESCE(v_missing, 0) <> 0 THEN
        RAISE EXCEPTION 'Spark personality memory archive SECDEF postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;

-- Downgrade:
-- BEGIN;
-- DROP FUNCTION IF EXISTS public.archive_spark_personality_memory(text, uuid, text);
-- COMMIT;
