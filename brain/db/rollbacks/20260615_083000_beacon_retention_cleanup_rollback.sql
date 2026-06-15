-- Rollback: restore Beacon tool events to strict append-only behavior.

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
    RAISE EXCEPTION 'alpha_internet_tool_events is append-only';
END;
$$;

COMMENT ON FUNCTION public.alpha_internet_tool_events_append_only() IS
    'Blocks Beacon tool-event update and delete mutation.';

COMMIT;
