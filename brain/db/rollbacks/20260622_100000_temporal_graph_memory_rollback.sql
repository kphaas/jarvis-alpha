-- Rollback for 20260622_100000_temporal_graph_memory.sql.
--
-- Refuses to drop graph tables once they contain operational data. This keeps
-- temporal memory history and audit rows from disappearing silently.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260622100000);

DO $preflight$
BEGIN
    IF to_regclass('public.alpha_memory_graph_audit') IS NOT NULL
       AND EXISTS (SELECT 1 FROM public.alpha_memory_graph_audit LIMIT 1) THEN
        RAISE EXCEPTION 'Refusing rollback: alpha_memory_graph_audit contains rows';
    END IF;

    IF to_regclass('public.alpha_memory_graph_proposals') IS NOT NULL
       AND EXISTS (SELECT 1 FROM public.alpha_memory_graph_proposals LIMIT 1) THEN
        RAISE EXCEPTION 'Refusing rollback: alpha_memory_graph_proposals contains rows';
    END IF;

    IF to_regclass('public.alpha_memory_graph_edges') IS NOT NULL
       AND EXISTS (SELECT 1 FROM public.alpha_memory_graph_edges LIMIT 1) THEN
        RAISE EXCEPTION 'Refusing rollback: alpha_memory_graph_edges contains rows';
    END IF;

    IF to_regclass('public.alpha_memory_graph_nodes') IS NOT NULL
       AND EXISTS (SELECT 1 FROM public.alpha_memory_graph_nodes LIMIT 1) THEN
        RAISE EXCEPTION 'Refusing rollback: alpha_memory_graph_nodes contains rows';
    END IF;
END
$preflight$;

DROP FUNCTION IF EXISTS public.memory_graph_health();
DROP FUNCTION IF EXISTS public.list_memory_graph_proposals(uuid, text, integer);
DROP FUNCTION IF EXISTS public.list_memory_graph_history(uuid, uuid, integer);
DROP FUNCTION IF EXISTS public.list_memory_graph_current(uuid, timestamptz, integer);
DROP FUNCTION IF EXISTS public.execute_memory_graph_proposal(uuid, uuid, text);
DROP FUNCTION IF EXISTS public.propose_memory_graph_write(
    uuid,
    text,
    text,
    jsonb,
    text,
    text,
    text
);

DROP TABLE IF EXISTS public.alpha_memory_graph_audit;
DROP TABLE IF EXISTS public.alpha_memory_graph_proposals;
DROP TABLE IF EXISTS public.alpha_memory_graph_edges;
DROP TABLE IF EXISTS public.alpha_memory_graph_nodes;

DO $postcheck$
DECLARE
    v_remaining INTEGER;
BEGIN
    SELECT COUNT(*)::INTEGER
      INTO v_remaining
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname IN (
           'alpha_memory_graph_nodes',
           'alpha_memory_graph_edges',
           'alpha_memory_graph_proposals',
           'alpha_memory_graph_audit'
       );

    IF COALESCE(v_remaining, 0) <> 0 THEN
        RAISE EXCEPTION 'Temporal graph memory rollback left graph tables behind';
    END IF;
END
$postcheck$;

COMMIT;
