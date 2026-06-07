-- AT-0 Herald mail ingestion foundation.
-- Stores Microsoft Graph message metadata/body previews and local draft proposals.
-- No mailbox writes, sends, deletes, or message moves are represented here.

BEGIN;

CREATE TABLE IF NOT EXISTS public.alpha_at0_mail_scan_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger             TEXT NOT NULL DEFAULT 'manual',
    status              TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'succeeded', 'failed')),
    started_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at         TIMESTAMPTZ,
    mailbox_count       INTEGER NOT NULL DEFAULT 0,
    max_results         INTEGER NOT NULL DEFAULT 25,
    messages_seen       INTEGER NOT NULL DEFAULT 0,
    messages_new        INTEGER NOT NULL DEFAULT 0,
    draft_proposals_created INTEGER NOT NULL DEFAULT 0,
    error_type          TEXT,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.alpha_at0_mail_messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mailbox             TEXT NOT NULL,
    graph_message_id    TEXT NOT NULL,
    internet_message_id TEXT,
    conversation_id     TEXT,
    sender_name         TEXT,
    sender_email        TEXT,
    subject             TEXT,
    received_at         TIMESTAMPTZ,
    body_preview        TEXT,
    body_preview_sha256 TEXT NOT NULL,
    web_link            TEXT,
    classification      TEXT NOT NULL DEFAULT 'unknown'
        CHECK (classification IN (
            'lead', 'support', 'press', 'partner', 'investor',
            'vendor', 'noise', 'unknown'
        )),
    priority            TEXT NOT NULL DEFAULT 'medium'
        CHECK (priority IN ('high', 'medium', 'low')),
    status              TEXT NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'triaged', 'drafted', 'archived')),
    classification_reason TEXT NOT NULL DEFAULT '',
    processed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (mailbox, graph_message_id)
);

CREATE TABLE IF NOT EXISTS public.alpha_at0_mail_draft_proposals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mail_message_id     UUID NOT NULL REFERENCES public.alpha_at0_mail_messages(id)
        ON DELETE CASCADE,
    mailbox             TEXT NOT NULL,
    recipient_email     TEXT,
    reply_subject       TEXT NOT NULL,
    proposed_body       TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'needs_review'
        CHECK (status IN ('needs_review', 'approved', 'rejected')),
    reviewer_notes      TEXT,
    reviewed_by         TEXT,
    reviewed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_at0_mail_scan_runs_started
    ON public.alpha_at0_mail_scan_runs(started_at DESC);

CREATE INDEX IF NOT EXISTS idx_at0_mail_messages_received
    ON public.alpha_at0_mail_messages(received_at DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_at0_mail_messages_status_class
    ON public.alpha_at0_mail_messages(status, classification, received_at DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_at0_mail_draft_status_created
    ON public.alpha_at0_mail_draft_proposals(status, created_at DESC);

ALTER TABLE public.alpha_at0_mail_scan_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_at0_mail_scan_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_at0_mail_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_at0_mail_messages FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_at0_mail_draft_proposals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_at0_mail_draft_proposals FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS at0_mail_scan_runs_select ON public.alpha_at0_mail_scan_runs;
CREATE POLICY at0_mail_scan_runs_select ON public.alpha_at0_mail_scan_runs
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS at0_mail_scan_runs_write ON public.alpha_at0_mail_scan_runs;
CREATE POLICY at0_mail_scan_runs_write ON public.alpha_at0_mail_scan_runs
    FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS at0_mail_scan_runs_update ON public.alpha_at0_mail_scan_runs;
CREATE POLICY at0_mail_scan_runs_update ON public.alpha_at0_mail_scan_runs
    FOR UPDATE
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS at0_mail_messages_select ON public.alpha_at0_mail_messages;
CREATE POLICY at0_mail_messages_select ON public.alpha_at0_mail_messages
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS at0_mail_messages_write ON public.alpha_at0_mail_messages;
CREATE POLICY at0_mail_messages_write ON public.alpha_at0_mail_messages
    FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS at0_mail_messages_update ON public.alpha_at0_mail_messages;
CREATE POLICY at0_mail_messages_update ON public.alpha_at0_mail_messages
    FOR UPDATE
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS at0_mail_draft_proposals_select ON public.alpha_at0_mail_draft_proposals;
CREATE POLICY at0_mail_draft_proposals_select ON public.alpha_at0_mail_draft_proposals
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS at0_mail_draft_proposals_write ON public.alpha_at0_mail_draft_proposals;
CREATE POLICY at0_mail_draft_proposals_write ON public.alpha_at0_mail_draft_proposals
    FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS at0_mail_draft_proposals_update ON public.alpha_at0_mail_draft_proposals;
CREATE POLICY at0_mail_draft_proposals_update ON public.alpha_at0_mail_draft_proposals
    FOR UPDATE
    USING (true)
    WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE ON public.alpha_at0_mail_scan_runs TO jarvis_alpha_writer;
GRANT SELECT, INSERT, UPDATE ON public.alpha_at0_mail_messages TO jarvis_alpha_writer;
GRANT SELECT, INSERT, UPDATE ON public.alpha_at0_mail_draft_proposals TO jarvis_alpha_writer;
GRANT SELECT ON public.alpha_at0_mail_scan_runs TO jarvis_alpha_app;
GRANT SELECT ON public.alpha_at0_mail_messages TO jarvis_alpha_app;
GRANT SELECT ON public.alpha_at0_mail_draft_proposals TO jarvis_alpha_app;

COMMENT ON TABLE public.alpha_at0_mail_messages IS
    'AT-0 Herald Microsoft Graph message ledger. Stores metadata, body preview, and hashes only; no full message body.';

COMMENT ON TABLE public.alpha_at0_mail_draft_proposals IS
    'Local Herald reply draft proposals awaiting human review. Does not write drafts back to Microsoft 365 or send mail.';

COMMIT;
