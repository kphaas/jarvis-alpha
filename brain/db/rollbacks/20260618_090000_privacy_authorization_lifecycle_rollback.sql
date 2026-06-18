-- Rollback: P5-A Privacy Agent authorization vault + removal lifecycle.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260618090001);

DROP INDEX IF EXISTS public.idx_privacy_evidence_removal_request;
ALTER TABLE IF EXISTS public.alpha_privacy_evidence_items
    DROP COLUMN IF EXISTS removal_request_id;

DROP TABLE IF EXISTS public.alpha_privacy_removal_request_events;
DROP TABLE IF EXISTS public.alpha_privacy_removal_requests;

COMMIT;
