-- Purpose: Beacon P3 internet evidence store.
-- Adds RLS-protected request/source/evidence tables plus append-only tool
-- events. Raw user queries are not stored; request shape and hashes are stored.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260606094500);

CREATE TABLE IF NOT EXISTS public.alpha_internet_requests (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             TEXT NOT NULL,
    requester           TEXT NOT NULL,
    selected_tool       TEXT NOT NULL
                        CHECK (selected_tool IN (
                            'search', 'fetch', 'extract', 'crawl', 'browser_use'
                        )),
    sensitivity         TEXT NOT NULL
                        CHECK (sensitivity IN (
                            'normal', 'privacy', 'legal', 'financial', 'minor'
                        )),
    policy_tier         TEXT NOT NULL
                        CHECK (policy_tier IN ('T1', 'T2', 'T3', 'T4', 'T5')),
    status              TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN (
                            'running', 'succeeded', 'failed', 'blocked'
                        )),
    request_payload_hash TEXT NOT NULL,
    request_shape       JSONB NOT NULL DEFAULT '{}'::jsonb,
    policy_reason       TEXT NOT NULL,
    blocked_reasons     JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_digest        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_internet_request_hash_check
        CHECK (request_payload_hash ~ '^sha256:[a-f0-9]{64}$'),
    CONSTRAINT alpha_internet_request_error_digest_check
        CHECK (error_digest IS NULL OR error_digest ~ '^sha256:[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_alpha_internet_requests_user_created
    ON public.alpha_internet_requests(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_internet_requests_status
    ON public.alpha_internet_requests(status);

ALTER TABLE public.alpha_internet_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_internet_requests FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS alpha_internet_requests_isolation
    ON public.alpha_internet_requests;
CREATE POLICY alpha_internet_requests_isolation
    ON public.alpha_internet_requests
    FOR ALL
    USING (
        user_id = current_setting('rls.user_id', true)
        OR current_setting('rls.role', true) = 'platform_admin'
    )
    WITH CHECK (
        user_id = current_setting('rls.user_id', true)
        OR current_setting('rls.role', true) = 'platform_admin'
    );

CREATE TABLE IF NOT EXISTS public.alpha_internet_sources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      UUID NOT NULL
                    REFERENCES public.alpha_internet_requests(id)
                    ON DELETE RESTRICT,
    url             TEXT NOT NULL,
    host            TEXT NOT NULL,
    title           TEXT,
    content_hash    TEXT NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_internet_sources_hash_check
        CHECK (content_hash ~ '^[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_alpha_internet_sources_request
    ON public.alpha_internet_sources(request_id);
CREATE INDEX IF NOT EXISTS idx_alpha_internet_sources_host
    ON public.alpha_internet_sources(host);

ALTER TABLE public.alpha_internet_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_internet_sources FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS alpha_internet_sources_isolation
    ON public.alpha_internet_sources;
CREATE POLICY alpha_internet_sources_isolation
    ON public.alpha_internet_sources
    FOR ALL
    USING (
        request_id IN (
            SELECT id
            FROM public.alpha_internet_requests
            WHERE user_id = current_setting('rls.user_id', true)
               OR current_setting('rls.role', true) = 'platform_admin'
        )
    )
    WITH CHECK (
        request_id IN (
            SELECT id
            FROM public.alpha_internet_requests
            WHERE user_id = current_setting('rls.user_id', true)
               OR current_setting('rls.role', true) = 'platform_admin'
        )
    );

CREATE TABLE IF NOT EXISTS public.alpha_internet_evidence (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      UUID NOT NULL
                    REFERENCES public.alpha_internet_requests(id)
                    ON DELETE RESTRICT,
    source_id       UUID NOT NULL
                    REFERENCES public.alpha_internet_sources(id)
                    ON DELETE RESTRICT,
    claim           TEXT NOT NULL,
    citation_text   TEXT NOT NULL,
    confidence      TEXT NOT NULL
                    CHECK (confidence IN ('low', 'medium', 'high')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alpha_internet_evidence_request
    ON public.alpha_internet_evidence(request_id);
CREATE INDEX IF NOT EXISTS idx_alpha_internet_evidence_source
    ON public.alpha_internet_evidence(source_id);

ALTER TABLE public.alpha_internet_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_internet_evidence FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS alpha_internet_evidence_isolation
    ON public.alpha_internet_evidence;
CREATE POLICY alpha_internet_evidence_isolation
    ON public.alpha_internet_evidence
    FOR ALL
    USING (
        request_id IN (
            SELECT id
            FROM public.alpha_internet_requests
            WHERE user_id = current_setting('rls.user_id', true)
               OR current_setting('rls.role', true) = 'platform_admin'
        )
    )
    WITH CHECK (
        request_id IN (
            SELECT id
            FROM public.alpha_internet_requests
            WHERE user_id = current_setting('rls.user_id', true)
               OR current_setting('rls.role', true) = 'platform_admin'
        )
    );

CREATE TABLE IF NOT EXISTS public.alpha_internet_tool_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      UUID NOT NULL
                    REFERENCES public.alpha_internet_requests(id)
                    ON DELETE RESTRICT,
    tool            TEXT NOT NULL
                    CHECK (tool IN (
                        'search', 'fetch', 'extract', 'crawl', 'browser_use'
                    )),
    event_type      TEXT NOT NULL,
    status          TEXT NOT NULL
                    CHECK (status IN ('started', 'succeeded', 'failed', 'blocked')),
    payload_hash    TEXT,
    error_digest    TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_internet_tool_event_payload_hash_check
        CHECK (payload_hash IS NULL OR payload_hash ~ '^sha256:[a-f0-9]{64}$'),
    CONSTRAINT alpha_internet_tool_event_error_digest_check
        CHECK (error_digest IS NULL OR error_digest ~ '^sha256:[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_alpha_internet_tool_events_request
    ON public.alpha_internet_tool_events(request_id, created_at);

ALTER TABLE public.alpha_internet_tool_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_internet_tool_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS alpha_internet_tool_events_isolation
    ON public.alpha_internet_tool_events;
CREATE POLICY alpha_internet_tool_events_isolation
    ON public.alpha_internet_tool_events
    FOR ALL
    USING (
        request_id IN (
            SELECT id
            FROM public.alpha_internet_requests
            WHERE user_id = current_setting('rls.user_id', true)
               OR current_setting('rls.role', true) = 'platform_admin'
        )
    )
    WITH CHECK (
        request_id IN (
            SELECT id
            FROM public.alpha_internet_requests
            WHERE user_id = current_setting('rls.user_id', true)
               OR current_setting('rls.role', true) = 'platform_admin'
        )
    );

CREATE OR REPLACE FUNCTION public.alpha_internet_touch_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_alpha_internet_requests_updated_at
    ON public.alpha_internet_requests;
CREATE TRIGGER trg_alpha_internet_requests_updated_at
    BEFORE UPDATE ON public.alpha_internet_requests
    FOR EACH ROW
    EXECUTE FUNCTION public.alpha_internet_touch_updated_at();

CREATE OR REPLACE FUNCTION public.alpha_internet_tool_events_append_only()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    RAISE EXCEPTION 'alpha_internet_tool_events is append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_alpha_internet_tool_events_no_update
    ON public.alpha_internet_tool_events;
CREATE TRIGGER trg_alpha_internet_tool_events_no_update
    BEFORE UPDATE ON public.alpha_internet_tool_events
    FOR EACH ROW
    EXECUTE FUNCTION public.alpha_internet_tool_events_append_only();

DROP TRIGGER IF EXISTS trg_alpha_internet_tool_events_no_delete
    ON public.alpha_internet_tool_events;
CREATE TRIGGER trg_alpha_internet_tool_events_no_delete
    BEFORE DELETE ON public.alpha_internet_tool_events
    FOR EACH ROW
    EXECUTE FUNCTION public.alpha_internet_tool_events_append_only();

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_internet_requests
            TO jarvis_alpha_app;
        GRANT SELECT, INSERT
            ON public.alpha_internet_sources,
               public.alpha_internet_evidence,
               public.alpha_internet_tool_events
            TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_internet_requests
            TO jarvis_alpha_writer;
        GRANT SELECT, INSERT
            ON public.alpha_internet_sources,
               public.alpha_internet_evidence,
               public.alpha_internet_tool_events
            TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON TABLE public.alpha_internet_requests IS
    'Beacon internet evidence requests. Raw user query text is not stored.';
COMMENT ON TABLE public.alpha_internet_tool_events IS
    'Append-only Beacon tool event ledger for public-egress evidence gathering.';

DO $postcheck$
DECLARE
    v_missing INTEGER;
BEGIN
    SELECT count(*)::INTEGER
    INTO v_missing
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname IN (
          'alpha_internet_requests',
          'alpha_internet_sources',
          'alpha_internet_evidence',
          'alpha_internet_tool_events'
      )
      AND NOT (c.relrowsecurity AND c.relforcerowsecurity);

    IF COALESCE(v_missing, 0) <> 0 THEN
        RAISE EXCEPTION 'Beacon internet evidence RLS postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;
