-- School email intelligence for Alpha-owned Gmail review.
-- Stores reviewed event candidates without persisting full email bodies.

BEGIN;

CREATE TABLE IF NOT EXISTS public.alpha_school_email_messages (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    gmail_message_id    TEXT NOT NULL UNIQUE,
    gmail_thread_id     TEXT,
    history_id          TEXT,
    mailbox             TEXT NOT NULL DEFAULT 'primary',
    sender              TEXT,
    subject             TEXT,
    received_at         TIMESTAMPTZ,
    snippet             TEXT,
    body_sha256         TEXT NOT NULL,
    classification      TEXT NOT NULL DEFAULT 'school'
        CHECK (classification IN ('school', 'not_school', 'needs_review')),
    processed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.alpha_school_event_candidates (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email_message_id    UUID NOT NULL REFERENCES public.alpha_school_email_messages(id)
        ON DELETE CASCADE,
    gmail_message_id    TEXT NOT NULL,
    source              TEXT NOT NULL DEFAULT 'gmail_mount_pisgah',
    school_name         TEXT NOT NULL DEFAULT 'Mount Pisgah',
    title               TEXT NOT NULL,
    event_date          DATE NOT NULL,
    event_time          TIME,
    end_time            TIME,
    location            TEXT,
    notes               TEXT,
    confidence          NUMERIC(5,4) NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'needs_review'
        CHECK (status IN ('needs_review', 'approved', 'imported', 'ignored')),
    family_external_id  TEXT NOT NULL UNIQUE,
    family_event_id     UUID,
    reviewed_by         TEXT,
    reviewed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_school_email_messages_received
    ON public.alpha_school_email_messages(received_at DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_school_event_candidates_status_date
    ON public.alpha_school_event_candidates(status, event_date ASC);

CREATE INDEX IF NOT EXISTS idx_school_event_candidates_gmail_message
    ON public.alpha_school_event_candidates(gmail_message_id);

ALTER TABLE public.alpha_school_email_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_school_event_candidates ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS school_email_messages_select ON public.alpha_school_email_messages;
CREATE POLICY school_email_messages_select ON public.alpha_school_email_messages
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS school_email_messages_write ON public.alpha_school_email_messages;
CREATE POLICY school_email_messages_write ON public.alpha_school_email_messages
    FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS school_email_messages_update ON public.alpha_school_email_messages;
CREATE POLICY school_email_messages_update ON public.alpha_school_email_messages
    FOR UPDATE
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS school_event_candidates_select ON public.alpha_school_event_candidates;
CREATE POLICY school_event_candidates_select ON public.alpha_school_event_candidates
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS school_event_candidates_write ON public.alpha_school_event_candidates;
CREATE POLICY school_event_candidates_write ON public.alpha_school_event_candidates
    FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS school_event_candidates_update ON public.alpha_school_event_candidates;
CREATE POLICY school_event_candidates_update ON public.alpha_school_event_candidates
    FOR UPDATE
    USING (true)
    WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE ON public.alpha_school_email_messages TO jarvis_alpha_writer;
GRANT SELECT, INSERT, UPDATE ON public.alpha_school_event_candidates TO jarvis_alpha_writer;
GRANT SELECT ON public.alpha_school_email_messages TO jarvis_alpha_app;
GRANT SELECT ON public.alpha_school_event_candidates TO jarvis_alpha_app;

COMMENT ON TABLE public.alpha_school_email_messages IS
    'Gmail message processing ledger for school email intelligence; stores metadata, snippets, and body hashes only.';
COMMENT ON TABLE public.alpha_school_event_candidates IS
    'Reviewed school-calendar candidates extracted from Gmail by Alpha for Family calendar import.';

COMMIT;
