-- Rollback: P5-B Privacy Agent Gateway dry-run proof columns.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260618100001);

UPDATE public.alpha_privacy_removal_request_events
SET event_type = 'note'
WHERE event_type = 'dry_run_prepared';

ALTER TABLE public.alpha_privacy_removal_request_events
    DROP CONSTRAINT IF EXISTS privacy_removal_request_events_event_type_check;
ALTER TABLE public.alpha_privacy_removal_request_events
    ADD CONSTRAINT privacy_removal_request_events_event_type_check
    CHECK (event_type IN (
        'created',
        'approved',
        'queued',
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

DROP INDEX IF EXISTS public.idx_privacy_removal_requests_dry_run_prepared;

ALTER TABLE public.alpha_privacy_removal_requests
    DROP CONSTRAINT IF EXISTS privacy_removal_request_gateway_idempotency_check,
    DROP CONSTRAINT IF EXISTS privacy_removal_request_dry_run_payload_hash_check,
    DROP COLUMN IF EXISTS gateway_idempotency_key_digest,
    DROP COLUMN IF EXISTS dry_run_prepared_at,
    DROP COLUMN IF EXISTS dry_run_payload_key_version,
    DROP COLUMN IF EXISTS dry_run_payload_hash,
    DROP COLUMN IF EXISTS dry_run_payload_ciphertext;

COMMIT;
