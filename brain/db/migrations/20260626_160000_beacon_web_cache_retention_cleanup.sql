-- Migration: 20260626_160000_beacon_web_cache_retention_cleanup
-- Purpose:   Allow reviewed Beacon retention cleanup to prune expired web-cache rows.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260626160000);

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT DELETE ON public.alpha_internet_web_cache TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT DELETE ON public.alpha_internet_web_cache TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON TABLE public.alpha_internet_web_cache IS
    'Beacon public-web cache of sanitized citation excerpts, indexed terms, content hashes, and reviewed retention cleanup for expired rows. Raw user query text is not stored.';

COMMIT;

-- Verified rollback:
-- REVOKE DELETE ON public.alpha_internet_web_cache FROM jarvis_alpha_app;
-- REVOKE DELETE ON public.alpha_internet_web_cache FROM jarvis_alpha_writer;
