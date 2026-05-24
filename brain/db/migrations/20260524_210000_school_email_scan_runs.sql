BEGIN;

CREATE TABLE IF NOT EXISTS public.alpha_school_email_scan_runs (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger                         TEXT NOT NULL DEFAULT 'manual'
        CHECK (trigger IN ('api', 'manual', 'nightly')),
    status                          TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at                     TIMESTAMPTZ,
    lookback_days                   INTEGER NOT NULL DEFAULT 1
        CHECK (lookback_days BETWEEN 1 AND 30),
    max_results                     INTEGER NOT NULL
        CHECK (max_results BETWEEN 1 AND 500),
    import_to_family                BOOLEAN NOT NULL DEFAULT true,
    manual_query                    BOOLEAN NOT NULL DEFAULT false,
    rules_loaded                    INTEGER NOT NULL DEFAULT 0,
    queries_run                     INTEGER NOT NULL DEFAULT 0,
    messages_seen                   INTEGER NOT NULL DEFAULT 0,
    messages_new                    INTEGER NOT NULL DEFAULT 0,
    event_candidates_created        INTEGER NOT NULL DEFAULT 0,
    action_candidates_created       INTEGER NOT NULL DEFAULT 0,
    events_imported                 INTEGER NOT NULL DEFAULT 0,
    actions_imported                INTEGER NOT NULL DEFAULT 0,
    import_errors                   INTEGER NOT NULL DEFAULT 0,
    error_type                      TEXT,
    error_message                   TEXT,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_school_email_scan_runs_started
    ON public.alpha_school_email_scan_runs(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_school_email_scan_runs_status
    ON public.alpha_school_email_scan_runs(status, started_at DESC);

ALTER TABLE public.alpha_school_email_scan_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_school_email_scan_runs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS school_email_scan_runs_select ON public.alpha_school_email_scan_runs;
CREATE POLICY school_email_scan_runs_select ON public.alpha_school_email_scan_runs
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS school_email_scan_runs_write ON public.alpha_school_email_scan_runs;
CREATE POLICY school_email_scan_runs_write ON public.alpha_school_email_scan_runs
    FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS school_email_scan_runs_update ON public.alpha_school_email_scan_runs;
CREATE POLICY school_email_scan_runs_update ON public.alpha_school_email_scan_runs
    FOR UPDATE
    USING (true)
    WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE ON public.alpha_school_email_scan_runs TO jarvis_alpha_writer;
GRANT SELECT ON public.alpha_school_email_scan_runs TO jarvis_alpha_app;

COMMENT ON TABLE public.alpha_school_email_scan_runs IS
    'Operational ledger for Alpha school Gmail scans; stores counts and sanitized failures, never email bodies.';

COMMIT;
