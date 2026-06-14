-- ADR-0026 PR-0 rollback: remove reviewed Dream consolidation semantic source.
-- Fails safely if rows already depend on dream_consolidated.

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.alpha_semantic_memory') IS NULL THEN
        RAISE EXCEPTION 'ADR-0026 source CHECK rollback preflight failed; alpha_semantic_memory table missing';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM public.alpha_semantic_memory
         WHERE source = 'dream_consolidated'
         LIMIT 1
    ) THEN
        RAISE EXCEPTION
            'ADR-0026 source CHECK rollback blocked; dream_consolidated rows exist';
    END IF;
END;
$$;

COMMIT;

ALTER TABLE public.alpha_semantic_memory
    DROP CONSTRAINT IF EXISTS alpha_semantic_memory_source_check;

ALTER TABLE public.alpha_semantic_memory
    ADD CONSTRAINT alpha_semantic_memory_source_check
    CHECK (source IN ('promoted', 'explicit', 'buddy'));

DO $$
DECLARE
    v_definition text;
BEGIN
    SELECT pg_get_constraintdef(c.oid)
      INTO v_definition
      FROM pg_constraint c
     WHERE c.conrelid = 'public.alpha_semantic_memory'::regclass
       AND c.conname = 'alpha_semantic_memory_source_check';

    IF v_definition IS NULL
       OR v_definition LIKE '%dream_consolidated%'
       OR v_definition NOT LIKE '%promoted%'
       OR v_definition NOT LIKE '%explicit%'
       OR v_definition NOT LIKE '%buddy%' THEN
        RAISE EXCEPTION 'ADR-0026 source CHECK rollback postcheck failed';
    END IF;
END;
$$;
