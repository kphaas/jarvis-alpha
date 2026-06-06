-- Rollback: remove P4 privacy removal control-plane metadata.
-- This is destructive for P4-only metadata and should be used only as a PR
-- rollback before relying on these tables in production.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260606173000);

DROP TRIGGER IF EXISTS trg_privacy_public_record_triage_updated_at
    ON public.alpha_privacy_public_record_triage;
DROP TRIGGER IF EXISTS trg_privacy_search_deindex_items_updated_at
    ON public.alpha_privacy_search_deindex_items;
DROP TRIGGER IF EXISTS trg_privacy_monitor_runs_updated_at
    ON public.alpha_privacy_monitor_runs;
DROP TRIGGER IF EXISTS trg_privacy_adapter_profiles_updated_at
    ON public.alpha_privacy_adapter_profiles;
DROP TRIGGER IF EXISTS trg_privacy_authorizations_updated_at
    ON public.alpha_privacy_authorizations;

DROP TABLE IF EXISTS public.alpha_privacy_public_record_triage;
DROP TABLE IF EXISTS public.alpha_privacy_search_deindex_items;
DROP TABLE IF EXISTS public.alpha_privacy_monitor_runs;
DROP TABLE IF EXISTS public.alpha_privacy_evidence_items;
DROP TABLE IF EXISTS public.alpha_privacy_adapter_profiles;
DROP TABLE IF EXISTS public.alpha_privacy_authorizations;

COMMIT;
