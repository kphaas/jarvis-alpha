-- 20260620_081000_buddy_event_retention_archive.sql
-- Purpose: keep alpha_buddy_events as a hot operational table by archiving
--          old low-priority rows and pruning the archive after a bounded window.

BEGIN;

CREATE TABLE IF NOT EXISTS public.alpha_buddy_events_archive (
    id UUID PRIMARY KEY,
    user_id TEXT,
    event_type TEXT NOT NULL CHECK (
        event_type IN ('alert', 'reminder', 'suggestion', 'system')
    ),
    title TEXT NOT NULL,
    body TEXT,
    priority INT NOT NULL DEFAULT 2,
    read BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL,
    source TEXT,
    payload JSONB,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    archive_reason TEXT NOT NULL DEFAULT 'low_priority_retention'
);

CREATE INDEX IF NOT EXISTS idx_buddy_events_archive_user_created
    ON public.alpha_buddy_events_archive (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_buddy_events_archive_archived_at
    ON public.alpha_buddy_events_archive (archived_at DESC);

ALTER TABLE public.alpha_buddy_events_archive ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS buddy_events_archive_isolation
    ON public.alpha_buddy_events_archive;
CREATE POLICY buddy_events_archive_isolation
    ON public.alpha_buddy_events_archive
    FOR ALL
    USING (
        current_setting('jarvis.role', true) = 'platform_admin'
        OR current_setting('rls.role', true) = 'platform_admin'
    )
    WITH CHECK (
        current_setting('jarvis.role', true) = 'platform_admin'
        OR current_setting('rls.role', true) = 'platform_admin'
    );

ALTER TABLE public.alpha_buddy_events_archive FORCE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, DELETE ON public.alpha_buddy_events_archive
    TO jarvis_alpha_writer;
GRANT SELECT, INSERT, DELETE ON public.alpha_buddy_events_archive
    TO jarvisbrain;

CREATE OR REPLACE FUNCTION public.archive_old_low_priority_buddy_events(
    p_hot_keep_days INTEGER DEFAULT 14,
    p_archive_keep_days INTEGER DEFAULT 180,
    p_batch_limit INTEGER DEFAULT 5000
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
    v_archived INTEGER := 0;
    v_pruned INTEGER := 0;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    PERFORM set_config('jarvis.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '60s';

    IF p_hot_keep_days < 1 THEN
        RAISE EXCEPTION 'archive_old_low_priority_buddy_events: p_hot_keep_days must be >= 1'
            USING ERRCODE = '22023';
    END IF;
    IF p_archive_keep_days < p_hot_keep_days THEN
        RAISE EXCEPTION 'archive_old_low_priority_buddy_events: p_archive_keep_days must be >= p_hot_keep_days'
            USING ERRCODE = '22023';
    END IF;
    IF p_batch_limit < 1 THEN
        RAISE EXCEPTION 'archive_old_low_priority_buddy_events: p_batch_limit must be >= 1'
            USING ERRCODE = '22023';
    END IF;

    WITH candidates AS (
        SELECT id
        FROM public.alpha_buddy_events
        WHERE priority <= 1
          AND created_at < now() - make_interval(days => p_hot_keep_days)
          AND COALESCE(source, '') <> 'restore_drill_alpha'
          AND title NOT ILIKE 'Restore drill%'
        ORDER BY created_at ASC, id ASC
        LIMIT p_batch_limit
        FOR UPDATE SKIP LOCKED
    ),
    moved AS (
        INSERT INTO public.alpha_buddy_events_archive (
            id,
            user_id,
            event_type,
            title,
            body,
            priority,
            read,
            created_at,
            source,
            payload,
            archived_at,
            archive_reason
        )
        SELECT
            e.id,
            e.user_id,
            e.event_type,
            e.title,
            e.body,
            e.priority,
            e.read,
            e.created_at,
            e.source,
            e.payload,
            now(),
            'low_priority_retention'
        FROM public.alpha_buddy_events e
        JOIN candidates c ON c.id = e.id
        ON CONFLICT (id) DO NOTHING
        RETURNING id
    ),
    deleted AS (
        DELETE FROM public.alpha_buddy_events e
        USING candidates c
        WHERE e.id = c.id
        RETURNING e.id
    )
    SELECT COUNT(*)::int INTO v_archived
    FROM deleted;

    WITH pruned AS (
        DELETE FROM public.alpha_buddy_events_archive
        WHERE archived_at < now() - make_interval(days => p_archive_keep_days)
        RETURNING id
    )
    SELECT COUNT(*)::int INTO v_pruned
    FROM pruned;

    RETURN jsonb_build_object(
        'archived_count', v_archived,
        'pruned_archive_count', v_pruned,
        'hot_keep_days', p_hot_keep_days,
        'archive_keep_days', p_archive_keep_days,
        'batch_limit', p_batch_limit
    );
END;
$function$;

REVOKE EXECUTE ON FUNCTION public.archive_old_low_priority_buddy_events(
    INTEGER,
    INTEGER,
    INTEGER
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.archive_old_low_priority_buddy_events(
    INTEGER,
    INTEGER,
    INTEGER
) TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.archive_old_low_priority_buddy_events(
    INTEGER,
    INTEGER,
    INTEGER
) TO jarvisbrain;

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
    v_buddy_retention JSONB := '{}'::jsonb;
    v_archived_buddy_events INTEGER := 0;
    v_pruned_buddy_event_archive INTEGER := 0;
    v_errors JSONB := '[]'::jsonb;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    PERFORM set_config('jarvis.role', 'platform_admin', true);
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
        v_buddy_retention := public.archive_old_low_priority_buddy_events(14, 180, 5000);
        v_archived_buddy_events := COALESCE(
            (v_buddy_retention->>'archived_count')::integer,
            0
        );
        v_pruned_buddy_event_archive := COALESCE(
            (v_buddy_retention->>'pruned_archive_count')::integer,
            0
        );
    EXCEPTION WHEN OTHERS THEN
        v_errors := v_errors || jsonb_build_object(
            'step', 'archive_buddy_events',
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
        'archived_buddy_events', v_archived_buddy_events,
        'pruned_buddy_event_archive', v_pruned_buddy_event_archive,
        'evicted_episodic', v_evicted_episodic,
        'capped_episodic', v_capped_episodic,
        'capped_semantic', v_capped_semantic,
        'errors', v_errors
    );
END;
$function$;

COMMENT ON TABLE public.alpha_buddy_events_archive IS
    'Bounded archive for low-priority Buddy events removed from alpha_buddy_events hot storage.';
COMMENT ON FUNCTION public.archive_old_low_priority_buddy_events IS
    'Archives priority<=1 Buddy rows after 14 days and prunes archive rows after 180 days.';
COMMENT ON FUNCTION public.run_buddy_memory_maintenance IS
    'Omnibus Buddy memory maintenance with low-priority Buddy event retention.';

COMMIT;
