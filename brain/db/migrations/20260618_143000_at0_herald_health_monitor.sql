-- Purpose: Durable health history for Herald Microsoft Graph read/send monitor.
-- Stores token role/read-path/send-state metadata only. No Graph tokens, message
-- bodies, or reply text are stored.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260618143000);

CREATE TABLE IF NOT EXISTS public.alpha_at0_mail_graph_health (
    id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status                 TEXT NOT NULL
                           CHECK (status IN ('ok', 'failed')),
    trigger                TEXT NOT NULL DEFAULT 'scheduled',
    checked_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    mailboxes_checked      INTEGER NOT NULL DEFAULT 0
                           CHECK (mailboxes_checked >= 0),
    messages_seen          INTEGER NOT NULL DEFAULT 0
                           CHECK (messages_seen >= 0),
    graph_roles            TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    missing_graph_roles    TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    current_send_failures  INTEGER NOT NULL DEFAULT 0
                           CHECK (current_send_failures >= 0),
    stuck_sending_count    INTEGER NOT NULL DEFAULT 0
                           CHECK (stuck_sending_count >= 0),
    last_sent_at           TIMESTAMPTZ,
    error_type             TEXT,
    error_message          TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alpha_at0_mail_graph_health_message_check
        CHECK (error_message IS NULL OR char_length(error_message) <= 240)
);

CREATE INDEX IF NOT EXISTS idx_at0_mail_graph_health_checked
    ON public.alpha_at0_mail_graph_health(checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_at0_mail_graph_health_status_checked
    ON public.alpha_at0_mail_graph_health(status, checked_at DESC);

ALTER TABLE public.alpha_at0_mail_graph_health ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_at0_mail_graph_health FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS at0_mail_graph_health_select
    ON public.alpha_at0_mail_graph_health;
CREATE POLICY at0_mail_graph_health_select
    ON public.alpha_at0_mail_graph_health
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS at0_mail_graph_health_write
    ON public.alpha_at0_mail_graph_health;
CREATE POLICY at0_mail_graph_health_write
    ON public.alpha_at0_mail_graph_health
    FOR INSERT
    WITH CHECK (true);

GRANT SELECT, INSERT ON public.alpha_at0_mail_graph_health TO jarvis_alpha_writer;
GRANT SELECT ON public.alpha_at0_mail_graph_health TO jarvis_alpha_app;

COMMENT ON TABLE public.alpha_at0_mail_graph_health IS
    'Herald Microsoft Graph health monitor history. Stores role/read/send-state metadata only; no tokens or mail body content.';

COMMIT;
