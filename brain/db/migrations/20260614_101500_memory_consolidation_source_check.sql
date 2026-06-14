-- ADR-0026 PR-0: allow reviewed Dream consolidation semantic provenance.
-- Scope: source CHECK only. No proposal, route, executor, or write behavior.

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.alpha_semantic_memory') IS NULL THEN
        RAISE EXCEPTION 'ADR-0026 source CHECK preflight failed; alpha_semantic_memory table missing';
    END IF;
END;
$$;

COMMIT;

ALTER TABLE public.alpha_semantic_memory
    DROP CONSTRAINT IF EXISTS alpha_semantic_memory_source_check;

ALTER TABLE public.alpha_semantic_memory
    ADD CONSTRAINT alpha_semantic_memory_source_check
    CHECK (source IN ('promoted', 'explicit', 'buddy', 'dream_consolidated'));

DO $$
DECLARE
    v_definition text;
BEGIN
    SELECT pg_get_constraintdef(c.oid)
      INTO v_definition
      FROM pg_constraint c
     WHERE c.conrelid = 'public.alpha_semantic_memory'::regclass
       AND c.conname = 'alpha_semantic_memory_source_check';

    IF v_definition IS NULL OR v_definition NOT LIKE '%dream_consolidated%' THEN
        RAISE EXCEPTION 'ADR-0026 source CHECK postcheck failed; dream_consolidated not allowed';
    END IF;
END;
$$;
