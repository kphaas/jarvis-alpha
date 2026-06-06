-- Rollback: remove the privacy case-draft completed status.
-- Safe downgrade path: completed cases return to submitted_for_approval before
-- the previous status constraint is restored.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260606111501);

UPDATE public.alpha_privacy_case_drafts
SET status = 'submitted_for_approval'
WHERE status = 'completed';

ALTER TABLE public.alpha_privacy_case_drafts
    DROP CONSTRAINT IF EXISTS alpha_privacy_case_drafts_status_check;

ALTER TABLE public.alpha_privacy_case_drafts
    ADD CONSTRAINT alpha_privacy_case_drafts_status_check
    CHECK (status IN (
        'draft',
        'submitted_for_approval',
        'archived'
    ));

COMMIT;
