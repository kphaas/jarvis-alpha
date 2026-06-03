-- Secret access audit is append-only runtime infrastructure.
-- Runtime app roles may execute the append function, but may not write the
-- FORCE-RLS table directly.

CREATE TABLE IF NOT EXISTS public.secret_access_log (
    id              BIGSERIAL PRIMARY KEY,
    key_name        TEXT NOT NULL,
    source          TEXT NOT NULL,
    accessed_at     TIMESTAMPTZ NOT NULL,
    node            TEXT NOT NULL,
    flushed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sal_key
    ON public.secret_access_log(key_name);

CREATE INDEX IF NOT EXISTS idx_sal_accessed
    ON public.secret_access_log(accessed_at DESC);

ALTER TABLE public.secret_access_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS secret_access_log_admin_select
    ON public.secret_access_log;
DROP POLICY IF EXISTS secret_access_log_admin_insert
    ON public.secret_access_log;

CREATE POLICY secret_access_log_admin_select
    ON public.secret_access_log
    FOR SELECT
    USING (current_setting('rls.role', true) = 'platform_admin');

CREATE POLICY secret_access_log_admin_insert
    ON public.secret_access_log
    FOR INSERT
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

ALTER TABLE public.secret_access_log FORCE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.record_secret_access(
    p_key_name TEXT,
    p_source TEXT,
    p_accessed_at TIMESTAMPTZ,
    p_node TEXT
) RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
BEGIN
    IF p_key_name IS NULL OR btrim(p_key_name) = '' THEN
        RAISE EXCEPTION 'record_secret_access: p_key_name must be non-empty';
    END IF;
    IF p_source IS NULL OR btrim(p_source) = '' THEN
        RAISE EXCEPTION 'record_secret_access: p_source must be non-empty';
    END IF;
    IF p_accessed_at IS NULL THEN
        RAISE EXCEPTION 'record_secret_access: p_accessed_at must be non-null';
    END IF;
    IF p_node IS NULL OR btrim(p_node) = '' THEN
        RAISE EXCEPTION 'record_secret_access: p_node must be non-empty';
    END IF;

    PERFORM set_config('rls.role', 'platform_admin', true);

    INSERT INTO public.secret_access_log (key_name, source, accessed_at, node)
    VALUES (p_key_name, p_source, p_accessed_at, p_node);
END;
$$;

REVOKE ALL ON FUNCTION public.record_secret_access(TEXT, TEXT, TIMESTAMPTZ, TEXT)
    FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.record_secret_access(TEXT, TEXT, TIMESTAMPTZ, TEXT)
    TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.record_secret_access(TEXT, TEXT, TIMESTAMPTZ, TEXT)
    TO jarvis_alpha_app;

GRANT SELECT ON public.secret_access_log TO jarvis_alpha_writer;
GRANT SELECT ON public.secret_access_log TO jarvis_alpha_app;
REVOKE INSERT, UPDATE, DELETE ON public.secret_access_log
    FROM PUBLIC, jarvis_alpha_writer, jarvis_alpha_app;

COMMENT ON FUNCTION public.record_secret_access(TEXT, TEXT, TIMESTAMPTZ, TEXT) IS
    'Append-only SECURITY DEFINER writer for secret_access_log under FORCE RLS.';
