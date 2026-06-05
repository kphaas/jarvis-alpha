-- Purpose: Close Porchlight RLS gap on privacy-scrub target metadata cache.
--
-- The cache is non-PII registry metadata, but Alpha's posture bar is that
-- every public table has RLS, FORCE RLS, and at least one policy. Maintenance
-- refreshes run with rls.role='platform_admin'.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260605073000);

DO $preflight$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'alpha_privacy_targets_cache'
    ) THEN
        RAISE EXCEPTION 'privacy targets cache RLS preflight failed; table missing';
    END IF;
END
$preflight$;

ALTER TABLE public.alpha_privacy_targets_cache ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS alpha_privacy_targets_cache_platform_admin
    ON public.alpha_privacy_targets_cache;

CREATE POLICY alpha_privacy_targets_cache_platform_admin
    ON public.alpha_privacy_targets_cache
    AS PERMISSIVE
    FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

ALTER TABLE public.alpha_privacy_targets_cache FORCE ROW LEVEL SECURITY;

DO $postcheck$
DECLARE
    v_policy_count INTEGER;
BEGIN
    SELECT count(*)::INTEGER
    INTO v_policy_count
    FROM pg_policy p
    JOIN pg_class c ON c.oid = p.polrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'alpha_privacy_targets_cache';

    IF EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = 'alpha_privacy_targets_cache'
          AND NOT (c.relrowsecurity AND c.relforcerowsecurity)
    ) OR COALESCE(v_policy_count, 0) = 0 THEN
        RAISE EXCEPTION 'privacy targets cache RLS postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;
