-- Rollback for 20260623_205000_memory_graph_valid_window_public_revoke.sql.
-- Restores PostgreSQL's default-style PUBLIC EXECUTE grant for the trigger
-- helper only. This rollback is intentionally narrow and does not drop graph
-- tables, triggers, or functions.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260623205001);

DO $function_exists$
BEGIN
    IF to_regprocedure('public.enforce_memory_graph_valid_window()') IS NULL THEN
        RAISE EXCEPTION 'missing function public.enforce_memory_graph_valid_window()';
    END IF;
END
$function_exists$;

GRANT EXECUTE ON FUNCTION public.enforce_memory_graph_valid_window()
    TO PUBLIC;

COMMIT;
