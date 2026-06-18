-- Purpose: Herald approved AT-0 Spark email reply send ledger.
-- Adds explicit send states to local draft proposals plus append-only send
-- events. Event payloads must not store draft body text or Graph tokens.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260618130000);

ALTER TABLE public.alpha_at0_mail_draft_proposals
    ADD COLUMN IF NOT EXISTS send_attempt_count INTEGER NOT NULL DEFAULT 0
        CHECK (send_attempt_count >= 0),
    ADD COLUMN IF NOT EXISTS last_send_attempt_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS send_failed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS send_error_type TEXT,
    ADD COLUMN IF NOT EXISTS send_error_message TEXT;

ALTER TABLE public.alpha_at0_mail_draft_proposals
    DROP CONSTRAINT IF EXISTS alpha_at0_mail_draft_proposals_status_check;
ALTER TABLE public.alpha_at0_mail_draft_proposals
    ADD CONSTRAINT alpha_at0_mail_draft_proposals_status_check
    CHECK (status IN (
        'needs_review', 'approved', 'rejected',
        'sending', 'sent', 'send_failed'
    ));

ALTER TABLE public.alpha_at0_mail_messages
    DROP CONSTRAINT IF EXISTS alpha_at0_mail_messages_status_check;
ALTER TABLE public.alpha_at0_mail_messages
    ADD CONSTRAINT alpha_at0_mail_messages_status_check
    CHECK (status IN (
        'new', 'triaged', 'drafted', 'archived',
        'sent', 'send_failed'
    ));

CREATE TABLE IF NOT EXISTS public.alpha_at0_mail_send_events (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    draft_proposal_id UUID NOT NULL
                      REFERENCES public.alpha_at0_mail_draft_proposals(id)
                      ON DELETE CASCADE,
    mail_message_id   UUID NOT NULL
                      REFERENCES public.alpha_at0_mail_messages(id)
                      ON DELETE CASCADE,
    mailbox           TEXT NOT NULL,
    graph_message_id  TEXT NOT NULL,
    event_type        TEXT NOT NULL
                      CHECK (event_type IN ('sending', 'sent', 'send_failed')),
    actor_sub         TEXT NOT NULL,
    actor_type        TEXT NOT NULL,
    http_status_code  INTEGER,
    error_type        TEXT,
    error_message     TEXT,
    event_payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alpha_at0_mail_send_events_actor_sub_check
        CHECK (char_length(btrim(actor_sub)) BETWEEN 1 AND 160),
    CONSTRAINT alpha_at0_mail_send_events_actor_type_check
        CHECK (char_length(btrim(actor_type)) BETWEEN 1 AND 80),
    CONSTRAINT alpha_at0_mail_send_events_payload_object_check
        CHECK (jsonb_typeof(event_payload) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_at0_mail_send_events_draft
    ON public.alpha_at0_mail_send_events(draft_proposal_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_at0_mail_send_events_mailbox_created
    ON public.alpha_at0_mail_send_events(mailbox, created_at DESC);

CREATE OR REPLACE FUNCTION public.alpha_at0_mail_send_events_immutable()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $$
BEGIN
    RAISE EXCEPTION 'alpha_at0_mail_send_events is append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_alpha_at0_mail_send_events_immutable
    ON public.alpha_at0_mail_send_events;
CREATE TRIGGER trg_alpha_at0_mail_send_events_immutable
    BEFORE UPDATE OR DELETE ON public.alpha_at0_mail_send_events
    FOR EACH ROW EXECUTE FUNCTION public.alpha_at0_mail_send_events_immutable();

ALTER TABLE public.alpha_at0_mail_send_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_at0_mail_send_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS at0_mail_send_events_select
    ON public.alpha_at0_mail_send_events;
CREATE POLICY at0_mail_send_events_select
    ON public.alpha_at0_mail_send_events
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS at0_mail_send_events_write
    ON public.alpha_at0_mail_send_events;
CREATE POLICY at0_mail_send_events_write
    ON public.alpha_at0_mail_send_events
    FOR INSERT
    WITH CHECK (true);

GRANT SELECT, INSERT ON public.alpha_at0_mail_send_events TO jarvis_alpha_writer;
GRANT SELECT ON public.alpha_at0_mail_send_events TO jarvis_alpha_app;

COMMENT ON TABLE public.alpha_at0_mail_send_events IS
    'Append-only Herald AT-0 email reply send audit. Stores metadata only; no tokens or reply body text.';

COMMIT;
