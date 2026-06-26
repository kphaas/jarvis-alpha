-- Migration: 20260626_120000_beacon_web_cache
-- Purpose:   Add a durable public-web evidence cache for Beacon rerank/index reuse.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260626120000);

CREATE TABLE IF NOT EXISTS public.alpha_internet_web_cache (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url_key             TEXT NOT NULL,
    url                 TEXT NOT NULL,
    host                TEXT NOT NULL,
    title               TEXT,
    content_hash        TEXT NOT NULL,
    excerpt             TEXT NOT NULL,
    search_terms        TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    fetched_at          TIMESTAMPTZ NOT NULL,
    expires_at          TIMESTAMPTZ NOT NULL,
    source_request_id   UUID
                        REFERENCES public.alpha_internet_requests(id)
                        ON DELETE SET NULL,
    access_count        INTEGER NOT NULL DEFAULT 0
                        CHECK (access_count >= 0),
    last_accessed_at    TIMESTAMPTZ,
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_internet_web_cache_content_hash_check
        CHECK (content_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT alpha_internet_web_cache_excerpt_length_check
        CHECK (char_length(excerpt) <= 1000),
    CONSTRAINT alpha_internet_web_cache_url_key_check
        CHECK (char_length(url_key) BETWEEN 8 AND 2048)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_alpha_internet_web_cache_url_key
    ON public.alpha_internet_web_cache(url_key);
CREATE INDEX IF NOT EXISTS idx_alpha_internet_web_cache_host
    ON public.alpha_internet_web_cache(host);
CREATE INDEX IF NOT EXISTS idx_alpha_internet_web_cache_expires_at
    ON public.alpha_internet_web_cache(expires_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_internet_web_cache_search_terms
    ON public.alpha_internet_web_cache USING GIN (search_terms);

ALTER TABLE public.alpha_internet_web_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_internet_web_cache FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS alpha_internet_web_cache_public_read_index
    ON public.alpha_internet_web_cache;
CREATE POLICY alpha_internet_web_cache_public_read_index
    ON public.alpha_internet_web_cache
    FOR ALL
    USING (
        current_setting('rls.role', true) IN ('platform_admin', 'user', 'child')
    )
    WITH CHECK (
        current_setting('rls.role', true) IN ('platform_admin', 'user', 'child')
    );

DROP TRIGGER IF EXISTS trg_alpha_internet_web_cache_updated_at
    ON public.alpha_internet_web_cache;
CREATE TRIGGER trg_alpha_internet_web_cache_updated_at
    BEFORE UPDATE ON public.alpha_internet_web_cache
    FOR EACH ROW
    EXECUTE FUNCTION public.alpha_internet_touch_updated_at();

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_internet_web_cache
            TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_internet_web_cache
            TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON TABLE public.alpha_internet_web_cache IS
    'Beacon public-web cache of sanitized citation excerpts, indexed terms, and content hashes. Raw user query text is not stored.';

DO $postcheck$
DECLARE
    v_missing INTEGER;
BEGIN
    SELECT count(*)::INTEGER
      INTO v_missing
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname = 'alpha_internet_web_cache'
       AND NOT (c.relrowsecurity AND c.relforcerowsecurity);

    IF COALESCE(v_missing, 0) <> 0 THEN
        RAISE EXCEPTION 'Beacon web cache RLS postcheck failed';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Beacon web cache OK';
END
$postcheck$;

COMMIT;

-- Verified rollback:
-- DROP TRIGGER IF EXISTS trg_alpha_internet_web_cache_updated_at
--     ON public.alpha_internet_web_cache;
-- DROP POLICY IF EXISTS alpha_internet_web_cache_public_read_index
--     ON public.alpha_internet_web_cache;
-- DROP TABLE IF EXISTS public.alpha_internet_web_cache;
