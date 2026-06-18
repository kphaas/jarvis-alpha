-- Purpose: P5-B Privacy Agent dry-run executor proof through Gateway egress only.
-- Adds encrypted dry-run payload proof to the local lifecycle ledger. It does
-- not enable broker submission, browser automation, email/SMS, or public API
-- calls from Brain.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260618100000);

DO $preflight$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'alpha_privacy_removal_requests'
    ) THEN
        RAISE EXCEPTION 'privacy gateway dry-run preflight failed; removal requests table missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'alpha_privacy_removal_request_events'
    ) THEN
        RAISE EXCEPTION 'privacy gateway dry-run preflight failed; request events table missing';
    END IF;
END
$preflight$;

ALTER TABLE public.alpha_privacy_removal_requests
    ADD COLUMN IF NOT EXISTS dry_run_payload_ciphertext BYTEA,
    ADD COLUMN IF NOT EXISTS dry_run_payload_hash TEXT,
    ADD COLUMN IF NOT EXISTS dry_run_payload_key_version TEXT,
    ADD COLUMN IF NOT EXISTS dry_run_prepared_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS gateway_idempotency_key_digest TEXT;

DO $constraints$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'privacy_removal_request_dry_run_payload_hash_check'
          AND conrelid = 'public.alpha_privacy_removal_requests'::regclass
    ) THEN
        ALTER TABLE public.alpha_privacy_removal_requests
            ADD CONSTRAINT privacy_removal_request_dry_run_payload_hash_check
            CHECK (
                dry_run_payload_hash IS NULL
                OR dry_run_payload_hash ~ '^sha256:[a-f0-9]{64}$'
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'privacy_removal_request_gateway_idempotency_check'
          AND conrelid = 'public.alpha_privacy_removal_requests'::regclass
    ) THEN
        ALTER TABLE public.alpha_privacy_removal_requests
            ADD CONSTRAINT privacy_removal_request_gateway_idempotency_check
            CHECK (
                gateway_idempotency_key_digest IS NULL
                OR gateway_idempotency_key_digest ~ '^hmac-sha256:[a-f0-9]{64}$'
            );
    END IF;
END
$constraints$;

CREATE INDEX IF NOT EXISTS idx_privacy_removal_requests_dry_run_prepared
    ON public.alpha_privacy_removal_requests(dry_run_prepared_at DESC)
    WHERE dry_run_prepared_at IS NOT NULL;

ALTER TABLE public.alpha_privacy_removal_request_events
    DROP CONSTRAINT IF EXISTS alpha_privacy_removal_request_events_event_type_check;
ALTER TABLE public.alpha_privacy_removal_request_events
    DROP CONSTRAINT IF EXISTS privacy_removal_request_events_event_type_check;
ALTER TABLE public.alpha_privacy_removal_request_events
    ADD CONSTRAINT privacy_removal_request_events_event_type_check
    CHECK (event_type IN (
        'created',
        'approved',
        'queued',
        'dry_run_prepared',
        'sent',
        'acknowledged',
        'monitoring',
        'completed',
        'failed',
        'escalated',
        'blocked',
        'proof_attached',
        'note'
    ));

COMMENT ON COLUMN public.alpha_privacy_removal_requests.dry_run_payload_ciphertext IS
    'Encrypted P5-B Gateway dry-run envelope and Gateway no-op response. No public egress payload is stored in plaintext.';
COMMENT ON COLUMN public.alpha_privacy_removal_requests.dry_run_payload_hash IS
    'Digest of encrypted P5-B Gateway dry-run proof payload.';
COMMENT ON COLUMN public.alpha_privacy_removal_requests.gateway_idempotency_key_digest IS
    'Keyed digest of the Gateway executor idempotency key; the raw key is not persisted.';

DO $postcheck$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relname IN (
            'alpha_privacy_removal_requests',
            'alpha_privacy_removal_request_events'
        )
        AND NOT (relrowsecurity AND relforcerowsecurity)
    ) THEN
        RAISE EXCEPTION 'privacy gateway dry-run FORCE RLS postcheck failed';
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
        RAISE EXCEPTION 'privacy gateway dry-run must not expose decrypt helpers';
    END IF;
END
$postcheck$;

COMMIT;
