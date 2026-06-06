-- Purpose: mark privacy review-packet cases as completed after all approved
-- actions reach terminal local workflow state. This adds no outbound execution
-- path and stores no plaintext.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260606111500);

DO $preflight$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'alpha_privacy_case_drafts'
    ) THEN
        RAISE EXCEPTION 'privacy completed status preflight failed; case drafts table missing';
    END IF;
END
$preflight$;

ALTER TABLE public.alpha_privacy_case_drafts
    DROP CONSTRAINT IF EXISTS alpha_privacy_case_drafts_status_check;

ALTER TABLE public.alpha_privacy_case_drafts
    ADD CONSTRAINT alpha_privacy_case_drafts_status_check
    CHECK (status IN (
        'draft',
        'submitted_for_approval',
        'archived',
        'completed'
    ));

COMMENT ON CONSTRAINT alpha_privacy_case_drafts_status_check
    ON public.alpha_privacy_case_drafts IS
    'Privacy review-packet cases may be completed only after local manual workflow reaches terminal action state.';

DO $postcheck$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'alpha_privacy_case_drafts_status_check'
          AND conrelid = 'public.alpha_privacy_case_drafts'::regclass
    ) THEN
        RAISE EXCEPTION 'privacy completed status postcheck failed; status constraint missing';
    END IF;
END
$postcheck$;

COMMIT;
