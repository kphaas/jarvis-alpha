BEGIN;

ALTER TABLE public.alpha_school_email_messages
    ADD COLUMN IF NOT EXISTS family_rule_id TEXT,
    ADD COLUMN IF NOT EXISTS child_member_id UUID,
    ADD COLUMN IF NOT EXISTS child_name TEXT;

ALTER TABLE public.alpha_school_event_candidates
    ADD COLUMN IF NOT EXISTS child_member_id UUID,
    ADD COLUMN IF NOT EXISTS child_name TEXT;

CREATE TABLE IF NOT EXISTS public.alpha_school_action_candidates (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email_message_id    UUID NOT NULL REFERENCES public.alpha_school_email_messages(id)
        ON DELETE CASCADE,
    gmail_message_id    TEXT NOT NULL,
    source              TEXT NOT NULL DEFAULT 'gmail_mount_pisgah',
    school_name         TEXT NOT NULL DEFAULT 'Mount Pisgah',
    child_member_id     UUID,
    child_name          TEXT,
    title               TEXT NOT NULL,
    action_date         DATE NOT NULL,
    action_time         TIME,
    notes               TEXT,
    confidence          NUMERIC(5,4) NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'needs_review'
        CHECK (status IN ('needs_review', 'approved', 'imported', 'ignored')),
    family_external_id  TEXT NOT NULL UNIQUE,
    family_action_id    UUID,
    reviewed_by         TEXT,
    reviewed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_school_action_candidates_status_date
    ON public.alpha_school_action_candidates(status, action_date ASC);

CREATE INDEX IF NOT EXISTS idx_school_action_candidates_gmail_message
    ON public.alpha_school_action_candidates(gmail_message_id);

ALTER TABLE public.alpha_school_email_messages FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_school_event_candidates FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_school_action_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_school_action_candidates FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS school_action_candidates_select ON public.alpha_school_action_candidates;
CREATE POLICY school_action_candidates_select ON public.alpha_school_action_candidates
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS school_action_candidates_write ON public.alpha_school_action_candidates;
CREATE POLICY school_action_candidates_write ON public.alpha_school_action_candidates
    FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS school_action_candidates_update ON public.alpha_school_action_candidates;
CREATE POLICY school_action_candidates_update ON public.alpha_school_action_candidates
    FOR UPDATE
    USING (true)
    WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE ON public.alpha_school_action_candidates TO jarvis_alpha_writer;
GRANT SELECT ON public.alpha_school_action_candidates TO jarvis_alpha_app;

COMMENT ON TABLE public.alpha_school_action_candidates IS
    'Parent action candidates extracted from school Gmail by Alpha for Family briefing import.';

COMMIT;
