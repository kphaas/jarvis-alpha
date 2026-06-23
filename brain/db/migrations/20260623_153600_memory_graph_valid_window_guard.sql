-- Purpose: keep temporal graph valid windows strict when a reviewed archive
-- executes in the same timestamp tick as the original create.
--
-- The graph tables intentionally require valid_to > valid_from. In live use,
-- an operator can create a reviewed test node/edge and immediately archive it;
-- PostgreSQL can evaluate both timestamps to the same value inside the
-- execution path, which violates the strict valid-window CHECK. This trigger
-- preserves the invariant without relaxing the constraint.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260623153600);

CREATE OR REPLACE FUNCTION public.enforce_memory_graph_valid_window()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO 'pg_catalog', 'public'
AS $function$
BEGIN
    IF NEW.valid_from IS NOT NULL
       AND NEW.valid_to IS NOT NULL
       AND NEW.valid_to <= NEW.valid_from THEN
        NEW.valid_to := NEW.valid_from + INTERVAL '1 millisecond';
    END IF;

    RETURN NEW;
END;
$function$;

DO $owner$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvisbrain') THEN
        EXECUTE 'ALTER FUNCTION public.enforce_memory_graph_valid_window() OWNER TO jarvisbrain';
    END IF;
END
$owner$;

DROP TRIGGER IF EXISTS alpha_memory_graph_nodes_valid_window_guard
    ON public.alpha_memory_graph_nodes;
CREATE TRIGGER alpha_memory_graph_nodes_valid_window_guard
    BEFORE INSERT OR UPDATE OF valid_from, valid_to
    ON public.alpha_memory_graph_nodes
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_memory_graph_valid_window();

DROP TRIGGER IF EXISTS alpha_memory_graph_edges_valid_window_guard
    ON public.alpha_memory_graph_edges;
CREATE TRIGGER alpha_memory_graph_edges_valid_window_guard
    BEFORE INSERT OR UPDATE OF valid_from, valid_to
    ON public.alpha_memory_graph_edges
    FOR EACH ROW
    EXECUTE FUNCTION public.enforce_memory_graph_valid_window();

COMMENT ON FUNCTION public.enforce_memory_graph_valid_window() IS
    'Preserves strict temporal graph valid_to > valid_from windows for same-tick reviewed archive actions.';

DO $postcheck$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_trigger
         WHERE tgname = 'alpha_memory_graph_nodes_valid_window_guard'
           AND NOT tgisinternal
    ) OR NOT EXISTS (
        SELECT 1
          FROM pg_trigger
         WHERE tgname = 'alpha_memory_graph_edges_valid_window_guard'
           AND NOT tgisinternal
    ) THEN
        RAISE EXCEPTION 'memory graph valid-window guard trigger postcheck failed';
    END IF;
END
$postcheck$;

COMMIT;
