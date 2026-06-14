-- Rollback: ADR-0026 archive_working executor and Buddy holds.
-- Fails safely if archive/hold metadata is in use.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260614120000);

DO $precheck$
BEGIN
    IF EXISTS (
        SELECT 1
          FROM public.alpha_conversation_memory
         WHERE COALESCE(consolidation_hold, false)
            OR consolidation_hold_proposal_id IS NOT NULL
            OR archived_at IS NOT NULL
            OR archived_by_proposal_id IS NOT NULL
         LIMIT 1
    ) THEN
        RAISE EXCEPTION
            'Refusing rollback: alpha_conversation_memory archive/hold metadata is in use';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM public.alpha_memory_consolidation_execution_ledger
         WHERE operation = 'archive_working'
         LIMIT 1
    ) THEN
        RAISE EXCEPTION
            'Refusing rollback: archive_working ledger rows exist';
    END IF;
END
$precheck$;

DROP FUNCTION IF EXISTS public.execute_memory_consolidation_archive(uuid, uuid, text);
DROP FUNCTION IF EXISTS public.revert_consolidation(uuid);
DROP FUNCTION IF EXISTS public.mark_memory_consolidation_archive_hold(uuid);

CREATE OR REPLACE FUNCTION public.evict_expired_working_memory()
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public', 'pg_temp'
AS $function$
DECLARE
  v_count INTEGER;
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  DELETE FROM public.alpha_conversation_memory
  WHERE tier = 'working'
    AND persistent = false
    AND created_at < now() - interval '24 hours';

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
EXCEPTION
  WHEN sqlstate '23503' OR sqlstate '23505' OR sqlstate '23514' OR sqlstate '23P01' THEN
    RAISE;
  WHEN sqlstate '40001' OR sqlstate '40P01' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'evict_expired_working_memory failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN 0;
END;
$function$;

CREATE OR REPLACE FUNCTION public.get_buddy_promotion_candidates(p_user_id text)
 RETURNS TABLE(id uuid, summary text)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'pg_catalog', 'public'
AS $function$
BEGIN
  PERFORM set_config('rls.role', 'platform_admin', true);
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';

  RETURN QUERY
    SELECT m.id, m.summary
    FROM public.alpha_conversation_memory m
    WHERE m.user_id = p_user_id
      AND m.tier = 'working'
      AND m.created_at < now() - interval '20 hours'
    LIMIT 5;
EXCEPTION
  WHEN integrity_constraint_violation THEN
    RAISE;
  WHEN transaction_rollback THEN
    RAISE;
  WHEN SQLSTATE '57014' OR SQLSTATE '55P03' THEN
    RAISE;
  WHEN OTHERS THEN
    RAISE WARNING 'get_buddy_promotion_candidates failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    RETURN;
END;
$function$;

ALTER TABLE public.alpha_conversation_memory
    DROP CONSTRAINT IF EXISTS alpha_conversation_memory_archived_by_proposal_fkey,
    DROP CONSTRAINT IF EXISTS alpha_conversation_memory_hold_proposal_fkey,
    DROP COLUMN IF EXISTS archived_by_proposal_id,
    DROP COLUMN IF EXISTS archived_at,
    DROP COLUMN IF EXISTS consolidation_hold_proposal_id,
    DROP COLUMN IF EXISTS consolidation_hold;

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT EXECUTE ON FUNCTION public.evict_expired_working_memory()
            TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.get_buddy_promotion_candidates(text)
            TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMIT;
