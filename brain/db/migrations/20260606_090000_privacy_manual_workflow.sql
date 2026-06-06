-- Purpose: P3-D through P3-G privacy manual workflow metadata.
-- Adds encrypted operator-note and evidence references for approved privacy
-- actions. This migration does not create an outbound execution path.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260606090000);

DO $preflight$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'alpha_privacy_actions'
    ) THEN
        RAISE EXCEPTION 'privacy manual workflow preflight failed; actions table missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'alpha_privacy_action_events'
    ) THEN
        RAISE EXCEPTION 'privacy manual workflow preflight failed; action events table missing';
    END IF;
END
$preflight$;

ALTER TABLE public.alpha_privacy_actions
    ADD COLUMN IF NOT EXISTS manual_disposition TEXT,
    ADD COLUMN IF NOT EXISTS manual_disposition_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS manual_disposition_by TEXT,
    ADD COLUMN IF NOT EXISTS manual_note_ciphertext BYTEA,
    ADD COLUMN IF NOT EXISTS manual_note_hash TEXT,
    ADD COLUMN IF NOT EXISTS evidence_payload_ciphertext BYTEA,
    ADD COLUMN IF NOT EXISTS evidence_payload_hash TEXT,
    ADD COLUMN IF NOT EXISTS workflow_payload_key_version TEXT;

DO $constraints$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'privacy_action_manual_disposition_check'
    ) THEN
        ALTER TABLE public.alpha_privacy_actions
            ADD CONSTRAINT privacy_action_manual_disposition_check
            CHECK (
                manual_disposition IS NULL
                OR manual_disposition IN ('handled', 'deferred', 'blocked')
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'privacy_action_manual_note_hash_check'
    ) THEN
        ALTER TABLE public.alpha_privacy_actions
            ADD CONSTRAINT privacy_action_manual_note_hash_check
            CHECK (
                manual_note_hash IS NULL
                OR manual_note_hash ~ '^sha256:[a-f0-9]{64}$'
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'privacy_action_evidence_payload_hash_check'
    ) THEN
        ALTER TABLE public.alpha_privacy_actions
            ADD CONSTRAINT privacy_action_evidence_payload_hash_check
            CHECK (
                evidence_payload_hash IS NULL
                OR evidence_payload_hash ~ '^sha256:[a-f0-9]{64}$'
            );
    END IF;
END
$constraints$;

CREATE INDEX IF NOT EXISTS idx_privacy_actions_manual_disposition
    ON public.alpha_privacy_actions(manual_disposition)
    WHERE manual_disposition IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_privacy_actions_workflow_due
    ON public.alpha_privacy_actions(verification_due_at)
    WHERE status IN ('approved', 'sent');

COMMENT ON COLUMN public.alpha_privacy_actions.manual_disposition IS
    'Operator-local workflow marker for approved privacy actions.';
COMMENT ON COLUMN public.alpha_privacy_actions.manual_note_ciphertext IS
    'Encrypted operator note payload for approved privacy action workflow.';
COMMENT ON COLUMN public.alpha_privacy_actions.evidence_payload_ciphertext IS
    'Encrypted evidence-reference payload for approved privacy action workflow.';

DO $postcheck$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'alpha_privacy_actions'
          AND column_name = 'manual_note_ciphertext'
    ) THEN
        RAISE EXCEPTION 'privacy manual workflow postcheck failed; encrypted note column missing';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_proc
        WHERE pronamespace = 'public'::regnamespace
          AND proname IN (
              'privacy_decrypt_payload',
              'get_privacy_payload',
              'read_privacy_payload'
          )
    ) THEN
        RAISE EXCEPTION 'privacy manual workflow must not expose decrypt helpers';
    END IF;
END
$postcheck$;

COMMIT;
