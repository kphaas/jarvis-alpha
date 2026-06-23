-- Rollback for 20260623_153600_memory_graph_valid_window_guard.sql.
-- Removes only the same-tick temporal graph valid-window guard.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260623153601);

DROP TRIGGER IF EXISTS alpha_memory_graph_nodes_valid_window_guard
    ON public.alpha_memory_graph_nodes;
DROP TRIGGER IF EXISTS alpha_memory_graph_edges_valid_window_guard
    ON public.alpha_memory_graph_edges;
DROP FUNCTION IF EXISTS public.enforce_memory_graph_valid_window();

COMMIT;
