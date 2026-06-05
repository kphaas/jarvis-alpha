-- Purpose: P2-E privacy review packet case drafts.
-- Adds an RLS-protected grouping table for multi-target draft packets and
-- links existing alpha_privacy_actions rows to that case. No outbound
-- execution path is created here.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260605120000);

DO $preflight$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'alpha_privacy_subjects'
    ) THEN
        RAISE EXCEPTION 'privacy case drafts preflight failed; subjects table missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'alpha_privacy_actions'
    ) THEN
        RAISE EXCEPTION 'privacy case drafts preflight failed; actions table missing';
    END IF;
END
$preflight$;

CREATE TABLE IF NOT EXISTS public.alpha_privacy_case_drafts (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id                  UUID NOT NULL
                               REFERENCES public.alpha_privacy_subjects(id)
                               ON DELETE RESTRICT,
    created_by_user_id          TEXT NOT NULL,
    target_count                INTEGER NOT NULL
                               CHECK (target_count > 0),
    status                      TEXT NOT NULL DEFAULT 'draft'
                               CHECK (status IN (
                                   'draft', 'submitted_for_approval', 'archived'
                               )),
    packet_payload_ciphertext    BYTEA NOT NULL,
    packet_payload_hash          TEXT NOT NULL,
    payload_key_version          TEXT NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT privacy_case_draft_packet_hash_check
        CHECK (packet_payload_hash ~ '^sha256:[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_privacy_case_drafts_subject
    ON public.alpha_privacy_case_drafts(subject_id);
CREATE INDEX IF NOT EXISTS idx_privacy_case_drafts_status
    ON public.alpha_privacy_case_drafts(status);
CREATE INDEX IF NOT EXISTS idx_privacy_case_drafts_created
    ON public.alpha_privacy_case_drafts(created_at DESC);

ALTER TABLE public.alpha_privacy_case_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_privacy_case_drafts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_case_drafts_isolation
    ON public.alpha_privacy_case_drafts;
CREATE POLICY privacy_case_drafts_isolation
    ON public.alpha_privacy_case_drafts
    FOR ALL
    USING (
        subject_id IN (
            SELECT id
            FROM public.alpha_privacy_subjects
            WHERE user_id = current_setting('rls.user_id', true)
               OR guardian_user_id = current_setting('rls.user_id', true)
               OR current_setting('rls.role', true) = 'platform_admin'
        )
    )
    WITH CHECK (
        subject_id IN (
            SELECT id
            FROM public.alpha_privacy_subjects
            WHERE user_id = current_setting('rls.user_id', true)
               OR guardian_user_id = current_setting('rls.user_id', true)
               OR current_setting('rls.role', true) = 'platform_admin'
        )
    );

ALTER TABLE public.alpha_privacy_actions
    ADD COLUMN IF NOT EXISTS case_draft_id UUID
    REFERENCES public.alpha_privacy_case_drafts(id)
    ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_privacy_actions_case_draft
    ON public.alpha_privacy_actions(case_draft_id)
    WHERE case_draft_id IS NOT NULL;

DROP TRIGGER IF EXISTS trg_privacy_case_drafts_updated_at
    ON public.alpha_privacy_case_drafts;
CREATE TRIGGER trg_privacy_case_drafts_updated_at
    BEFORE UPDATE ON public.alpha_privacy_case_drafts
    FOR EACH ROW
    EXECUTE FUNCTION public.privacy_scrub_touch_updated_at();

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_privacy_case_drafts
            TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_privacy_case_drafts
            TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON TABLE public.alpha_privacy_case_drafts IS
    'RLS-protected privacy-scrub review packet cases. Packet payloads are encrypted; no outbound execution is represented here.';

DO $postcheck$
DECLARE
    v_policy_count INTEGER;
BEGIN
    SELECT count(*)::INTEGER
    INTO v_policy_count
    FROM pg_policy p
    JOIN pg_class c ON c.oid = p.polrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'alpha_privacy_case_drafts';

    IF EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = 'alpha_privacy_case_drafts'
          AND NOT (c.relrowsecurity AND c.relforcerowsecurity)
    ) OR COALESCE(v_policy_count, 0) = 0 THEN
        RAISE EXCEPTION 'privacy case drafts RLS postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;
