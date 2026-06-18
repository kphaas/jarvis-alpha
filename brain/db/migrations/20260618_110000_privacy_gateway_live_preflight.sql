-- Purpose: P5-C Privacy Agent one-target live preflight through Gateway egress.
-- Adds encrypted live-preflight proof metadata for the BeenVerified adapter.
-- Gateway remains the only public egress owner; the kill switch defaults off.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260618110000);

DO $preflight$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'alpha_privacy_removal_requests'
    ) THEN
        RAISE EXCEPTION 'privacy gateway live preflight failed; removal requests table missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'alpha_privacy_removal_request_events'
    ) THEN
        RAISE EXCEPTION 'privacy gateway live preflight failed; request events table missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'alpha_approval_queue'
    ) THEN
        RAISE EXCEPTION 'privacy gateway live preflight failed; approval queue table missing';
    END IF;
END
$preflight$;

ALTER TABLE public.alpha_privacy_removal_requests
    ADD COLUMN IF NOT EXISTS live_preflight_payload_ciphertext BYTEA,
    ADD COLUMN IF NOT EXISTS live_preflight_payload_hash TEXT,
    ADD COLUMN IF NOT EXISTS live_preflight_payload_key_version TEXT,
    ADD COLUMN IF NOT EXISTS live_preflight_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS live_preflight_status TEXT,
    ADD COLUMN IF NOT EXISTS live_preflight_approval_queue_id UUID;

DO $constraints$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'privacy_removal_request_live_preflight_hash_check'
          AND conrelid = 'public.alpha_privacy_removal_requests'::regclass
    ) THEN
        ALTER TABLE public.alpha_privacy_removal_requests
            ADD CONSTRAINT privacy_removal_request_live_preflight_hash_check
            CHECK (
                live_preflight_payload_hash IS NULL
                OR live_preflight_payload_hash ~ '^sha256:[a-f0-9]{64}$'
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'privacy_removal_request_live_preflight_status_check'
          AND conrelid = 'public.alpha_privacy_removal_requests'::regclass
    ) THEN
        ALTER TABLE public.alpha_privacy_removal_requests
            ADD CONSTRAINT privacy_removal_request_live_preflight_status_check
            CHECK (
                live_preflight_status IS NULL
                OR live_preflight_status IN (
                    'live_disabled',
                    'live_preflight_passed',
                    'live_preflight_failed'
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'privacy_removal_request_live_preflight_approval_fk'
          AND conrelid = 'public.alpha_privacy_removal_requests'::regclass
    ) THEN
        ALTER TABLE public.alpha_privacy_removal_requests
            ADD CONSTRAINT privacy_removal_request_live_preflight_approval_fk
            FOREIGN KEY (live_preflight_approval_queue_id)
            REFERENCES public.alpha_approval_queue(id)
            ON DELETE RESTRICT;
    END IF;
END
$constraints$;

CREATE INDEX IF NOT EXISTS idx_privacy_removal_requests_live_preflight_at
    ON public.alpha_privacy_removal_requests(live_preflight_at DESC)
    WHERE live_preflight_at IS NOT NULL;

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
        'live_preflight_blocked',
        'live_preflight_passed',
        'live_preflight_failed',
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

COMMENT ON COLUMN public.alpha_privacy_removal_requests.live_preflight_payload_ciphertext IS
    'Encrypted P5-C Gateway live-preflight envelope and Gateway response. No broker form payload is stored in plaintext.';
COMMENT ON COLUMN public.alpha_privacy_removal_requests.live_preflight_payload_hash IS
    'Digest of encrypted P5-C Gateway live-preflight proof payload.';
COMMENT ON COLUMN public.alpha_privacy_removal_requests.live_preflight_status IS
    'Gateway live-preflight result: kill switch disabled, fixed target GET passed, or fixed target GET failed.';
COMMENT ON COLUMN public.alpha_privacy_removal_requests.live_preflight_approval_queue_id IS
    'Fresh approved alpha_approval_queue item bound to this live-preflight attempt.';

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
        RAISE EXCEPTION 'privacy gateway live preflight FORCE RLS postcheck failed';
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
        RAISE EXCEPTION 'privacy gateway live preflight must not expose decrypt helpers';
    END IF;
END
$postcheck$;

COMMIT;
