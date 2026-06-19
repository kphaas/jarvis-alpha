-- Rollback ADR-0027 semantic memory provenance and review lane.
-- Refuses to drop columns while review state or non-empty provenance is in use.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260618120000);

DO $preflight$
DECLARE
    v_reviewed INTEGER;
    v_provenance INTEGER;
BEGIN
    IF to_regclass('public.alpha_semantic_memory') IS NULL THEN
        RAISE EXCEPTION 'semantic memory provenance rollback preflight failed; alpha_semantic_memory missing';
    END IF;

    SELECT count(*)::INTEGER
      INTO v_reviewed
      FROM public.alpha_semantic_memory
     WHERE review_status IS DISTINCT FROM 'active'
        OR review_reason IS NOT NULL
        OR reviewed_at IS NOT NULL
        OR reviewed_by IS NOT NULL;

    IF COALESCE(v_reviewed, 0) <> 0 THEN
        RAISE EXCEPTION 'Refusing rollback: semantic memory review state is in use';
    END IF;

    SELECT count(*)::INTEGER
      INTO v_provenance
      FROM public.alpha_semantic_memory
     WHERE provenance IS NOT NULL
       AND provenance <> '{}'::jsonb;

    IF COALESCE(v_provenance, 0) <> 0 THEN
        RAISE EXCEPTION 'Refusing rollback: semantic memory provenance is in use';
    END IF;
END
$preflight$;

DROP FUNCTION IF EXISTS public.review_semantic_memory(UUID, UUID, TEXT, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.save_semantic_memory_with_provenance(UUID, TEXT, TEXT, JSONB, TEXT, TEXT);

CREATE OR REPLACE FUNCTION public.save_semantic_memory(p_user_id uuid, p_fact text, p_category text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
DECLARE
  v_inserted INTEGER;
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  INSERT INTO public.alpha_semantic_memory
    (user_id, fact, category, source)
  SELECT
    p_user_id, p_fact, p_category, 'explicit'
  WHERE (
    SELECT COUNT(*)
    FROM public.alpha_semantic_memory
    WHERE user_id = p_user_id
  ) < 50;

  GET DIAGNOSTICS v_inserted = ROW_COUNT;

  IF v_inserted = 0 THEN
    RETURN jsonb_build_object('saved', false, 'reason', 'cap_reached');
  END IF;

  RETURN jsonb_build_object(
    'saved', true,
    'fact', p_fact,
    'category', p_category
  );
EXCEPTION
  WHEN integrity_constraint_violation THEN
    RAISE;
  WHEN transaction_rollback THEN
    RAISE;
  WHEN SQLSTATE '57014' OR SQLSTATE '55P03' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'save_semantic_memory failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN jsonb_build_object('saved', false, 'reason', 'error');
END;
$function$;

DROP INDEX IF EXISTS public.idx_asm_user_review_status;

ALTER TABLE public.alpha_semantic_memory
    DROP CONSTRAINT IF EXISTS alpha_semantic_memory_review_status_check;

ALTER TABLE public.alpha_semantic_memory
    DROP COLUMN IF EXISTS provenance,
    DROP COLUMN IF EXISTS review_status,
    DROP COLUMN IF EXISTS review_reason,
    DROP COLUMN IF EXISTS reviewed_at,
    DROP COLUMN IF EXISTS reviewed_by;

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT EXECUTE ON FUNCTION public.save_semantic_memory(UUID, TEXT, TEXT) TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT EXECUTE ON FUNCTION public.save_semantic_memory(UUID, TEXT, TEXT) TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMIT;
