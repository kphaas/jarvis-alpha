-- Rollback for 20260620_081000_buddy_event_retention_archive.sql.
-- Fails safely when archived rows exist so audit data is not dropped silently.

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.alpha_buddy_events_archive') IS NOT NULL
       AND EXISTS (SELECT 1 FROM public.alpha_buddy_events_archive LIMIT 1) THEN
        RAISE EXCEPTION
            'Refusing rollback: alpha_buddy_events_archive contains rows';
    END IF;
END $$;

DROP FUNCTION IF EXISTS public.archive_old_low_priority_buddy_events(
    INTEGER,
    INTEGER,
    INTEGER
);

DROP TABLE IF EXISTS public.alpha_buddy_events_archive;

CREATE OR REPLACE FUNCTION public.run_buddy_memory_maintenance(p_user_id TEXT)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
    v_evicted_working INTEGER := 0;
    v_evicted_episodic INTEGER := 0;
    v_capped_episodic INTEGER := 0;
    v_capped_semantic INTEGER := 0;
    v_errors JSONB := '[]'::jsonb;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '60s';

    IF p_user_id IS NULL OR p_user_id = '' THEN
        RAISE EXCEPTION 'run_buddy_memory_maintenance: p_user_id required'
            USING ERRCODE = '22023';
    END IF;

    BEGIN
        v_evicted_working := public.evict_expired_working_memory();
    EXCEPTION WHEN OTHERS THEN
        v_errors := v_errors || jsonb_build_object(
            'step', 'evict_working',
            'error', SQLERRM
        );
    END;

    BEGIN
        v_evicted_episodic := public.evict_episodic_memory_older_than(p_user_id, 30);
    EXCEPTION WHEN OTHERS THEN
        v_errors := v_errors || jsonb_build_object(
            'step', 'evict_episodic',
            'error', SQLERRM
        );
    END;

    BEGIN
        v_capped_episodic := public.cap_episodic_memory(p_user_id, 1000);
    EXCEPTION WHEN OTHERS THEN
        v_errors := v_errors || jsonb_build_object(
            'step', 'cap_episodic',
            'error', SQLERRM
        );
    END;

    BEGIN
        v_capped_semantic := public.cap_semantic_memory(p_user_id, 200);
    EXCEPTION WHEN OTHERS THEN
        v_errors := v_errors || jsonb_build_object(
            'step', 'cap_semantic',
            'error', SQLERRM
        );
    END;

    RETURN jsonb_build_object(
        'user_id', p_user_id,
        'evicted_working', v_evicted_working,
        'evicted_episodic', v_evicted_episodic,
        'capped_episodic', v_capped_episodic,
        'capped_semantic', v_capped_semantic,
        'errors', v_errors
    );
END;
$function$;

COMMENT ON FUNCTION public.run_buddy_memory_maintenance IS
    'Omnibus Buddy memory maintenance without low-priority Buddy event retention.';

COMMIT;
