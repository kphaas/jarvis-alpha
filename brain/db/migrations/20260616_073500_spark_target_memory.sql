-- Purpose: Dedicated reviewed Spark target-memory lane.
-- This keeps selected-recipient facts and open loops separate from
-- principal voice/personality memory and grounds only the chosen draft target.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260616073500);

CREATE TABLE IF NOT EXISTS public.alpha_spark_target_memory (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    principal_id        TEXT NOT NULL,
    target_ref_hash     TEXT NOT NULL,
    target_label        TEXT NOT NULL,
    kind                TEXT NOT NULL
                        CHECK (kind IN (
                            'profile_fact', 'preference', 'open_loop'
                        )),
    content             TEXT NOT NULL,
    source              TEXT NOT NULL DEFAULT 'thread_mark'
                        CHECK (source IN ('thread_mark')),
    evidence_ref_hash   TEXT,
    importance_score    DOUBLE PRECISION NOT NULL DEFAULT 0.8
                        CHECK (importance_score >= 0 AND importance_score <= 1),
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'archived')),
    approved_by         TEXT NOT NULL,
    approved_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_spark_target_memory_principal_check
        CHECK (principal_id ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    CONSTRAINT alpha_spark_target_memory_target_hash_check
        CHECK (target_ref_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT alpha_spark_target_memory_target_label_length_check
        CHECK (char_length(btrim(target_label)) BETWEEN 1 AND 120),
    CONSTRAINT alpha_spark_target_memory_content_length_check
        CHECK (char_length(btrim(content)) BETWEEN 1 AND 500),
    CONSTRAINT alpha_spark_target_memory_approved_by_check
        CHECK (char_length(btrim(approved_by)) BETWEEN 1 AND 128),
    CONSTRAINT alpha_spark_target_memory_evidence_hash_check
        CHECK (evidence_ref_hash IS NULL OR evidence_ref_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT alpha_spark_target_memory_unique_active
        UNIQUE (principal_id, target_ref_hash, kind, content)
);

CREATE INDEX IF NOT EXISTS idx_alpha_spark_target_memory_principal_target_active
    ON public.alpha_spark_target_memory(
        principal_id,
        target_ref_hash,
        status,
        importance_score DESC,
        updated_at DESC
    );
CREATE INDEX IF NOT EXISTS idx_alpha_spark_target_memory_kind
    ON public.alpha_spark_target_memory(kind, updated_at DESC);

ALTER TABLE public.alpha_spark_target_memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_spark_target_memory FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS alpha_spark_target_memory_read_isolation
    ON public.alpha_spark_target_memory;
CREATE POLICY alpha_spark_target_memory_read_isolation
    ON public.alpha_spark_target_memory
    FOR SELECT
    USING (
        principal_id = lower(current_setting('rls.user_id', true))
        OR current_setting('rls.role', true) = 'platform_admin'
    );

DROP POLICY IF EXISTS alpha_spark_target_memory_write_admin
    ON public.alpha_spark_target_memory;
CREATE POLICY alpha_spark_target_memory_write_admin
    ON public.alpha_spark_target_memory
    FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

CREATE OR REPLACE FUNCTION public.list_spark_target_memory(
    p_principal_id text,
    p_target_ref_hash text,
    p_limit integer DEFAULT 12
)
RETURNS TABLE (
    id text,
    principal_id text,
    target_ref_hash text,
    target_label text,
    kind text,
    content text,
    source text,
    evidence_ref_hash text,
    importance_score double precision,
    approved_by text,
    approved_at timestamptz,
    created_at timestamptz,
    updated_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $$
DECLARE
    v_principal text := lower(btrim(p_principal_id));
    v_target_ref_hash text := lower(btrim(p_target_ref_hash));
    v_limit integer := LEAST(GREATEST(COALESCE(p_limit, 12), 1), 24);
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    IF v_principal !~ '^[a-z0-9][a-z0-9_-]{0,63}$' THEN
        RETURN;
    END IF;
    IF v_target_ref_hash !~ '^[a-f0-9]{64}$' THEN
        RETURN;
    END IF;

    RETURN QUERY
    SELECT
        m.id::text,
        m.principal_id,
        m.target_ref_hash,
        m.target_label,
        m.kind,
        m.content,
        m.source,
        m.evidence_ref_hash,
        m.importance_score,
        m.approved_by,
        m.approved_at,
        m.created_at,
        m.updated_at
    FROM public.alpha_spark_target_memory AS m
    WHERE m.principal_id = v_principal
      AND m.target_ref_hash = v_target_ref_hash
      AND m.status = 'active'
    ORDER BY
        CASE m.kind
            WHEN 'open_loop' THEN 0
            WHEN 'preference' THEN 1
            ELSE 2
        END,
        m.importance_score DESC,
        m.updated_at DESC,
        m.created_at DESC
    LIMIT v_limit;
END;
$$;

CREATE OR REPLACE FUNCTION public.save_spark_target_memory(
    p_principal_id text,
    p_target_ref_hash text,
    p_target_label text,
    p_kind text,
    p_content text,
    p_source text,
    p_evidence_ref_hash text,
    p_approved_by text,
    p_importance_score double precision DEFAULT 0.8
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $$
DECLARE
    v_principal text := lower(btrim(p_principal_id));
    v_target_ref_hash text := lower(btrim(p_target_ref_hash));
    v_target_label text := btrim(p_target_label);
    v_kind text := lower(btrim(p_kind));
    v_source text := lower(btrim(COALESCE(p_source, 'thread_mark')));
    v_content text := btrim(p_content);
    v_approved_by text := btrim(p_approved_by);
    v_evidence_hash text := NULLIF(lower(btrim(COALESCE(p_evidence_ref_hash, ''))), '');
    v_importance double precision := COALESCE(p_importance_score, 0.8);
    v_id uuid;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    IF v_principal !~ '^[a-z0-9][a-z0-9_-]{0,63}$' THEN
        RETURN jsonb_build_object('saved', false, 'reason', 'invalid_principal');
    END IF;
    IF v_target_ref_hash !~ '^[a-f0-9]{64}$' THEN
        RETURN jsonb_build_object('saved', false, 'reason', 'invalid_target_ref_hash');
    END IF;
    IF v_target_label IS NULL OR char_length(v_target_label) < 1 OR char_length(v_target_label) > 120 THEN
        RETURN jsonb_build_object('saved', false, 'reason', 'invalid_target_label');
    END IF;
    IF v_kind NOT IN ('profile_fact', 'preference', 'open_loop') THEN
        RETURN jsonb_build_object('saved', false, 'reason', 'invalid_kind');
    END IF;
    IF v_source NOT IN ('thread_mark') THEN
        RETURN jsonb_build_object('saved', false, 'reason', 'invalid_source');
    END IF;
    IF v_content IS NULL OR char_length(v_content) < 1 OR char_length(v_content) > 500 THEN
        RETURN jsonb_build_object('saved', false, 'reason', 'invalid_content');
    END IF;
    IF v_approved_by IS NULL OR char_length(v_approved_by) < 1 OR char_length(v_approved_by) > 128 THEN
        RETURN jsonb_build_object('saved', false, 'reason', 'invalid_approved_by');
    END IF;
    IF v_evidence_hash IS NOT NULL AND v_evidence_hash !~ '^[a-f0-9]{64}$' THEN
        RETURN jsonb_build_object('saved', false, 'reason', 'invalid_evidence_hash');
    END IF;
    IF v_importance < 0 OR v_importance > 1 THEN
        RETURN jsonb_build_object('saved', false, 'reason', 'invalid_importance');
    END IF;

    INSERT INTO public.alpha_spark_target_memory (
        principal_id,
        target_ref_hash,
        target_label,
        kind,
        content,
        source,
        evidence_ref_hash,
        importance_score,
        status,
        approved_by,
        approved_at,
        archived_at,
        updated_at
    )
    VALUES (
        v_principal,
        v_target_ref_hash,
        v_target_label,
        v_kind,
        v_content,
        v_source,
        v_evidence_hash,
        v_importance,
        'active',
        v_approved_by,
        NOW(),
        NULL,
        NOW()
    )
    ON CONFLICT (principal_id, target_ref_hash, kind, content)
    DO UPDATE SET
        target_label = EXCLUDED.target_label,
        source = EXCLUDED.source,
        evidence_ref_hash = COALESCE(
            EXCLUDED.evidence_ref_hash,
            public.alpha_spark_target_memory.evidence_ref_hash
        ),
        importance_score = GREATEST(
            public.alpha_spark_target_memory.importance_score,
            EXCLUDED.importance_score
        ),
        status = 'active',
        approved_by = EXCLUDED.approved_by,
        approved_at = NOW(),
        archived_at = NULL,
        updated_at = NOW()
    RETURNING id INTO v_id;

    RETURN jsonb_build_object(
        'saved', true,
        'target_memory_id', v_id,
        'principal_id', v_principal,
        'target_ref_hash', v_target_ref_hash,
        'kind', v_kind,
        'source', v_source
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.archive_spark_target_memory(
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

    UPDATE public.alpha_spark_target_memory
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
        'target_memory_id',
        p_memory_id,
        'principal_id',
        v_principal,
        'archived_by',
        v_archived_by
    );
END;
$$;

REVOKE ALL ON FUNCTION public.list_spark_target_memory(text, text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.save_spark_target_memory(
    text, text, text, text, text, text, text, text, double precision
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.archive_spark_target_memory(text, uuid, text) FROM PUBLIC;

DO $owner$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvisbrain') THEN
        EXECUTE
            'ALTER FUNCTION public.list_spark_target_memory'
            || '(text, text, integer) OWNER TO jarvisbrain';
        EXECUTE
            'ALTER FUNCTION public.save_spark_target_memory'
            || '(text, text, text, text, text, text, text, text, double precision) OWNER TO jarvisbrain';
        EXECUTE
            'ALTER FUNCTION public.archive_spark_target_memory'
            || '(text, uuid, text) OWNER TO jarvisbrain';
    END IF;
END
$owner$;

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT SELECT ON public.alpha_spark_target_memory TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.list_spark_target_memory(
            text, text, integer
        ) TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.save_spark_target_memory(
            text, text, text, text, text, text, text, text, double precision
        ) TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.archive_spark_target_memory(
            text, uuid, text
        ) TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT SELECT ON public.alpha_spark_target_memory TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.list_spark_target_memory(
            text, text, integer
        ) TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.save_spark_target_memory(
            text, text, text, text, text, text, text, text, double precision
        ) TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.archive_spark_target_memory(
            text, uuid, text
        ) TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON TABLE public.alpha_spark_target_memory IS
    'Reviewed Spark recipient-scoped memory used only for the selected reply target.';
COMMENT ON FUNCTION public.list_spark_target_memory(text, text, integer) IS
    'Bounded active Spark target-memory reader for one principal and one selected reply target.';
COMMENT ON FUNCTION public.save_spark_target_memory(text, text, text, text, text, text, text, text, double precision) IS
    'Reviewed Spark target-memory writer. Stores recipient-scoped facts and open loops with evidence hashes only.';
COMMENT ON FUNCTION public.archive_spark_target_memory(text, uuid, text) IS
    'Reviewed Spark target-memory archive action. Removes memory from active grounding without deleting it.';

DO $postcheck$
DECLARE
    v_missing INTEGER;
BEGIN
    SELECT count(*)::INTEGER
    INTO v_missing
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'alpha_spark_target_memory'
      AND NOT (c.relrowsecurity AND c.relforcerowsecurity);

    IF COALESCE(v_missing, 0) <> 0 THEN
        RAISE EXCEPTION 'Spark target memory RLS postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;

-- Downgrade:
-- BEGIN;
-- DROP FUNCTION IF EXISTS public.archive_spark_target_memory(text, uuid, text);
-- DROP FUNCTION IF EXISTS public.save_spark_target_memory(text, text, text, text, text, text, text, text, double precision);
-- DROP FUNCTION IF EXISTS public.list_spark_target_memory(text, text, integer);
-- DROP TABLE IF EXISTS public.alpha_spark_target_memory;
-- COMMIT;
