-- Rollback: P5-C Privacy Agent Gateway live-preflight proof columns.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260618110001);

UPDATE public.alpha_privacy_removal_request_events
SET event_type = 'note'
WHERE event_type IN (
    'live_preflight_blocked',
    'live_preflight_passed',
    'live_preflight_failed'
);

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

DROP INDEX IF EXISTS public.idx_privacy_removal_requests_live_preflight_at;

ALTER TABLE public.alpha_privacy_removal_requests
    DROP CONSTRAINT IF EXISTS privacy_removal_request_live_preflight_approval_fk,
    DROP CONSTRAINT IF EXISTS privacy_removal_request_live_preflight_status_check,
    DROP CONSTRAINT IF EXISTS privacy_removal_request_live_preflight_hash_check,
    DROP COLUMN IF EXISTS live_preflight_approval_queue_id,
    DROP COLUMN IF EXISTS live_preflight_status,
    DROP COLUMN IF EXISTS live_preflight_at,
    DROP COLUMN IF EXISTS live_preflight_payload_key_version,
    DROP COLUMN IF EXISTS live_preflight_payload_hash,
    DROP COLUMN IF EXISTS live_preflight_payload_ciphertext;

COMMIT;
