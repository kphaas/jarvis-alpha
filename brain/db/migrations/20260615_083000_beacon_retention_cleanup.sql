-- Purpose: Allow reviewed Beacon retention cleanup to delete expired tool
-- events without weakening the default append-only event ledger.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260615083000);

CREATE OR REPLACE FUNCTION public.alpha_internet_tool_events_append_only()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    IF TG_OP = 'DELETE'
       AND current_setting('app.beacon_retention_cleanup', true) = 'true'
       AND current_setting('rls.role', true) = 'platform_admin' THEN
        RETURN OLD;
    END IF;

    RAISE EXCEPTION 'alpha_internet_tool_events is append-only';
END;
$$;

COMMENT ON FUNCTION public.alpha_internet_tool_events_append_only() IS
    'Blocks Beacon tool-event mutation except reviewed retention cleanup deletes.';

COMMIT;
