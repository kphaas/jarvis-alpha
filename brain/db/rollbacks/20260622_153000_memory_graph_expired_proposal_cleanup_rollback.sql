BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260622153001);

DROP FUNCTION IF EXISTS public.expire_stale_memory_graph_proposals();

COMMIT;
