BEGIN;

CREATE TABLE IF NOT EXISTS public.alpha_gmail_oauth_health (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status                          TEXT NOT NULL
        CHECK (status IN ('ok', 'failed')),
    trigger                         TEXT NOT NULL DEFAULT 'api'
        CHECK (trigger IN ('api', 'manual', 'scheduled')),
    checked_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_successful_refresh_at      TIMESTAMPTZ,
    token_expires_in                INTEGER,
    scope                           TEXT,
    error_type                      TEXT,
    error_subtype                   TEXT,
    error_message                   TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_gmail_oauth_health_checked
    ON public.alpha_gmail_oauth_health(checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_gmail_oauth_health_status
    ON public.alpha_gmail_oauth_health(status, checked_at DESC);

ALTER TABLE public.alpha_gmail_oauth_health ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_gmail_oauth_health FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS gmail_oauth_health_select ON public.alpha_gmail_oauth_health;
CREATE POLICY gmail_oauth_health_select ON public.alpha_gmail_oauth_health
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS gmail_oauth_health_insert ON public.alpha_gmail_oauth_health;
CREATE POLICY gmail_oauth_health_insert ON public.alpha_gmail_oauth_health
    FOR INSERT
    WITH CHECK (true);

GRANT SELECT, INSERT ON public.alpha_gmail_oauth_health TO jarvis_alpha_writer;
GRANT SELECT ON public.alpha_gmail_oauth_health TO jarvis_alpha_app;

COMMENT ON TABLE public.alpha_gmail_oauth_health IS
    'Operational ledger for Alpha Gmail OAuth refresh checks; stores status only, never tokens or email bodies.';

COMMIT;
