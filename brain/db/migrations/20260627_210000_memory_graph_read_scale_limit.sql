-- Migration: 20260627_210000_memory_graph_read_scale_limit
-- Purpose: allow Helm's large graph view to request up to 1000 active graph nodes.

DO $$
DECLARE
    v_function text;
BEGIN
    SELECT pg_get_functiondef(
        'public.list_memory_graph_current(uuid,timestamp with time zone,integer)'::regprocedure
    )
    INTO v_function;

    IF v_function IS NULL THEN
        RAISE EXCEPTION 'public.list_memory_graph_current(uuid,timestamptz,integer) is missing';
    END IF;

    IF v_function NOT LIKE '%LEAST(GREATEST(COALESCE(p_limit, 100), 1), 500)%' THEN
        RAISE EXCEPTION 'list_memory_graph_current limit clamp is not at expected 500 baseline';
    END IF;

    EXECUTE replace(
        v_function,
        'LEAST(GREATEST(COALESCE(p_limit, 100), 1), 500)',
        'LEAST(GREATEST(COALESCE(p_limit, 100), 1), 1000)'
    );
END;
$$;
