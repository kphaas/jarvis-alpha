-- ============================================================================
-- 066_fix_expire_pending_approvals_rollback.sql
--
-- Restores the pre-066 broken expire_pending_approvals() function.
-- Use ONLY if 066 introduces an unforeseen regression. Restoring
-- reintroduces the P0003 multi-row bug — strongly recommend fixing
-- forward (writing 067), not rolling back.
-- ============================================================================

\set ON_ERROR_STOP on
\timing on

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

SELECT pg_advisory_xact_lock(72619066);

-- Restore broken pre-066 version (verbatim from production 2026-05-08)
CREATE OR REPLACE FUNCTION public.expire_pending_approvals()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
    v_expired_ids uuid[];
    v_count integer;
BEGIN
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    UPDATE public.alpha_approval_queue
    SET status = 'expired'
    WHERE status = 'pending' AND expires_at < NOW()
    RETURNING id
    INTO v_expired_ids;

    GET DIAGNOSTICS v_count = ROW_COUNT;

    IF v_count = 0 THEN
        RETURN 0;
    END IF;

    INSERT INTO public.alpha_approval_audit
        (approval_id, action_class, risk_tier, actor_sub, actor_type,
         description, parameters_hash, nonce, decision, decided_by, overnight)
    SELECT
        q.id, q.action_class, q.risk_tier, q.actor_sub, q.actor_type,
        q.description, q.parameters_hash, gen_random_uuid()::text,
        'expired', 'system', false
    FROM public.alpha_approval_queue q
    WHERE q.id = ANY(v_expired_ids);

    RETURN v_count;

EXCEPTION
    WHEN sqlstate '23503' OR sqlstate '23505' OR sqlstate '23514' OR sqlstate '23P01' THEN
        RAISE;
    WHEN sqlstate '40001' OR sqlstate '40P01' THEN
        RAISE;
    WHEN OTHERS THEN
        RAISE WARNING 'expire_pending_approvals failed: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
        RETURN 0;
END;
$function$;

DELETE FROM schema_migrations
WHERE filename = '066_fix_expire_pending_approvals.sql';

COMMIT;

\echo '=== 066 rolled back ==='
\echo 'WARNING: P0003 multi-row bug reinstated. Function will fail every 60s when >=2 rows expire.'
