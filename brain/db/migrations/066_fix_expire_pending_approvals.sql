-- ============================================================================
-- 066_fix_expire_pending_approvals.sql
--
-- TD-201 surgical fix: rewrite expire_pending_approvals() with multi-row
-- safe pattern (CTE chain) replacing broken `RETURNING id INTO uuid[]`.
--
-- Bug: original function used `RETURNING id INTO v_expired_ids` where
-- v_expired_ids is uuid[]. PL/pgSQL `RETURNING ... INTO` raises P0003
-- ('query returned more than one row') when >=2 rows match. Function
-- failed every 60s when the queue had >=2 expired pending rows, never
-- making progress. Caught 2026-05-07 evening as root cause of UI 500
-- on DELETE /v1/threads. See HANDOFF_2026-05-07_01.md ADDENDUM 2026-05-08.
--
-- Fix: chain UPDATE -> INSERT in a single multi-CTE statement. Multi-row
-- safe (no INTO scalar), atomic, and removes the redundant SELECT against
-- alpha_approval_queue that the original used to populate the audit insert.
--
-- Scope: TD-201 P0003 fix only. Does NOT add the
-- set_config('rls.role','platform_admin', true) SECDEF+FORCE-RLS escalation
-- — that audit is Slab 4's job (systematic pass over every SECDEF function
-- on a FORCE-RLS table). Currently safe because jarvisbrain is superuser
-- with BYPASSRLS.
--
-- Applied direct via psql per Q2=A pattern. Atomic transaction.
-- ============================================================================

\set ON_ERROR_STOP on
\timing on

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

SELECT pg_advisory_xact_lock(72619066);

-- PRE-FLIGHT: function exists
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_proc
    WHERE proname = 'expire_pending_approvals'
    AND pronamespace = 'public'::regnamespace
  ) THEN
    RAISE EXCEPTION 'PRE-FLIGHT FAIL: function public.expire_pending_approvals not found';
  END IF;
  RAISE NOTICE 'PRE-FLIGHT PASS: function exists, will replace';
END $$;

-- ----------------------------------------------------------------------------
-- The fix
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.expire_pending_approvals()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
    v_count integer;
BEGIN
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    -- Multi-row safe: chain UPDATE -> INSERT in a single CTE statement.
    -- Replaces broken `RETURNING id INTO v_expired_ids` (P0003 multi-row).
    WITH expired AS (
        UPDATE public.alpha_approval_queue
        SET status = 'expired'
        WHERE status = 'pending' AND expires_at < NOW()
        RETURNING id, action_class, risk_tier, actor_sub, actor_type,
                  description, parameters_hash
    ), audited AS (
        INSERT INTO public.alpha_approval_audit
            (approval_id, action_class, risk_tier, actor_sub, actor_type,
             description, parameters_hash, nonce, decision, decided_by, overnight)
        SELECT
            id, action_class, risk_tier, actor_sub, actor_type,
            description, parameters_hash, gen_random_uuid()::text,
            'expired', 'system', false
        FROM expired
        RETURNING approval_id
    )
    SELECT count(*)::integer INTO v_count FROM audited;

    RETURN COALESCE(v_count, 0);

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

-- POST-FLIGHT: function definition has CTE pattern, no broken RETURNING INTO
DO $$
DECLARE
    v_def text;
BEGIN
    SELECT pg_get_functiondef('expire_pending_approvals'::regproc) INTO v_def;

    IF v_def NOT LIKE '%WITH expired AS%' THEN
        RAISE EXCEPTION 'POST-FLIGHT FAIL: function missing expected CTE pattern';
    END IF;
    IF v_def LIKE '%RETURNING id%INTO v_expired_ids%' THEN
        RAISE EXCEPTION 'POST-FLIGHT FAIL: function still has broken RETURNING INTO pattern';
    END IF;
    IF v_def NOT LIKE '%audited AS%' THEN
        RAISE EXCEPTION 'POST-FLIGHT FAIL: function missing audited CTE';
    END IF;
    RAISE NOTICE 'POST-FLIGHT PASS: function uses CTE pattern, broken RETURNING INTO removed';
END $$;

-- Track migration
INSERT INTO schema_migrations (filename, checksum, source)
VALUES (
  '066_fix_expire_pending_approvals.sql',
  :'checksum',
  'runner'
)
ON CONFLICT (filename) DO UPDATE
  SET checksum = EXCLUDED.checksum,
      applied_at = NOW();

COMMIT;

\echo '=== 066 fix_expire_pending_approvals applied successfully ==='
\echo 'Multi-row safe CTE pattern replaces broken RETURNING INTO uuid[].'
\echo 'Watch pg log for absence of P0003 warnings when >=2 rows expire concurrently.'
