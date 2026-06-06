-- Purpose: Beacon P10 reviewed evidence promotion into semantic memory.
-- Promotion is source-bound, reviewed, and anti-poisoning aware. Raw web text is
-- never auto-ingested into memory.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260606120000);

CREATE TABLE IF NOT EXISTS public.alpha_internet_memory_promotions (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id            UUID NOT NULL
                          REFERENCES public.alpha_internet_requests(id)
                          ON DELETE RESTRICT,
    target_user_id        UUID NOT NULL,
    requested_by          TEXT NOT NULL,
    source_url            TEXT NOT NULL,
    source_host           TEXT NOT NULL,
    source_content_hash   TEXT NOT NULL,
    citation_text         TEXT NOT NULL,
    proposed_fact         TEXT NOT NULL,
    category              TEXT NOT NULL
                          CHECK (category IN (
                              'preference', 'person', 'project', 'constraint',
                              'health', 'child_profile'
                          )),
    status                TEXT NOT NULL DEFAULT 'pending_review'
                          CHECK (status IN (
                              'pending_review', 'rejected', 'promoted',
                              'skipped', 'failed'
                          )),
    reviewer_note         TEXT,
    reviewed_by           TEXT,
    reviewed_at           TIMESTAMPTZ,
    semantic_result       JSONB NOT NULL DEFAULT '{}'::jsonb,
    semantic_saved_at     TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_internet_memory_promotions_hash_check
        CHECK (source_content_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT alpha_internet_memory_promotions_fact_length_check
        CHECK (char_length(proposed_fact) BETWEEN 1 AND 500),
    CONSTRAINT alpha_internet_memory_promotions_citation_length_check
        CHECK (char_length(citation_text) BETWEEN 1 AND 1000)
);

CREATE INDEX IF NOT EXISTS idx_alpha_internet_memory_promotions_request
    ON public.alpha_internet_memory_promotions(request_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_internet_memory_promotions_requested_by
    ON public.alpha_internet_memory_promotions(requested_by, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_internet_memory_promotions_status
    ON public.alpha_internet_memory_promotions(status, created_at DESC);

ALTER TABLE public.alpha_internet_memory_promotions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_internet_memory_promotions FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS alpha_internet_memory_promotions_isolation
    ON public.alpha_internet_memory_promotions;
CREATE POLICY alpha_internet_memory_promotions_isolation
    ON public.alpha_internet_memory_promotions
    FOR ALL
    USING (
        requested_by = current_setting('rls.user_id', true)
        OR current_setting('rls.role', true) = 'platform_admin'
    )
    WITH CHECK (
        requested_by = current_setting('rls.user_id', true)
        OR current_setting('rls.role', true) = 'platform_admin'
    );

CREATE OR REPLACE FUNCTION public.save_beacon_semantic_memory(
    p_user_id uuid,
    p_fact text,
    p_category text,
    p_source_url text,
    p_source_content_hash text
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $$
DECLARE
    v_existing uuid;
    v_inserted uuid;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    IF p_category NOT IN (
        'preference', 'person', 'project', 'constraint', 'health', 'child_profile'
    ) THEN
        RETURN jsonb_build_object('saved', false, 'reason', 'invalid_category');
    END IF;
    IF p_fact IS NULL OR btrim(p_fact) = '' OR char_length(p_fact) > 500 THEN
        RETURN jsonb_build_object('saved', false, 'reason', 'invalid_fact');
    END IF;
    IF p_source_content_hash !~ '^[a-f0-9]{64}$' THEN
        RETURN jsonb_build_object('saved', false, 'reason', 'invalid_source_hash');
    END IF;

    SELECT id INTO v_existing
    FROM public.alpha_semantic_memory
    WHERE user_id = p_user_id
      AND fact = btrim(p_fact)
    LIMIT 1;

    IF v_existing IS NOT NULL THEN
        RETURN jsonb_build_object(
            'saved', false,
            'reason', 'duplicate',
            'semantic_id', v_existing,
            'source_url', p_source_url,
            'source_content_hash', p_source_content_hash
        );
    END IF;

    IF (
        SELECT COUNT(*)
        FROM public.alpha_semantic_memory
        WHERE user_id = p_user_id
    ) >= 50 THEN
        RETURN jsonb_build_object('saved', false, 'reason', 'cap_reached');
    END IF;

    INSERT INTO public.alpha_semantic_memory
        (user_id, fact, category, source)
    VALUES (p_user_id, btrim(p_fact), p_category, 'promoted')
    RETURNING id INTO v_inserted;

    RETURN jsonb_build_object(
        'saved', true,
        'semantic_id', v_inserted,
        'fact', btrim(p_fact),
        'category', p_category,
        'source', 'promoted',
        'source_url', p_source_url,
        'source_content_hash', p_source_content_hash
    );
EXCEPTION
    WHEN unique_violation THEN
        RETURN jsonb_build_object('saved', false, 'reason', 'duplicate');
END;
$$;

REVOKE ALL ON FUNCTION public.save_beacon_semantic_memory(
    uuid, text, text, text, text
) FROM PUBLIC;

DO $owner$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvisbrain') THEN
        EXECUTE
            'ALTER FUNCTION public.save_beacon_semantic_memory'
            || '(uuid, text, text, text, text) OWNER TO jarvisbrain';
    END IF;
END
$owner$;

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_internet_memory_promotions
            TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.save_beacon_semantic_memory(
            uuid, text, text, text, text
        ) TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_internet_memory_promotions
            TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.save_beacon_semantic_memory(
            uuid, text, text, text, text
        ) TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON TABLE public.alpha_internet_memory_promotions IS
    'Reviewed Beacon evidence promotion records. Stores provenance for semantic facts derived from public internet evidence.';
COMMENT ON FUNCTION public.save_beacon_semantic_memory(uuid, text, text, text, text) IS
    'Reviewed Beacon-only semantic memory writer. Writes source=promoted and returns dedup/cap result JSON.';

DO $postcheck$
DECLARE
    v_missing INTEGER;
BEGIN
    SELECT count(*)::INTEGER
    INTO v_missing
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'alpha_internet_memory_promotions'
      AND NOT (c.relrowsecurity AND c.relforcerowsecurity);

    IF COALESCE(v_missing, 0) <> 0 THEN
        RAISE EXCEPTION 'Beacon memory promotions RLS postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;

-- Downgrade:
-- BEGIN;
-- DROP FUNCTION IF EXISTS public.save_beacon_semantic_memory(uuid, text, text, text, text);
-- DROP TABLE IF EXISTS public.alpha_internet_memory_promotions;
-- COMMIT;
