-- Migration: 20260511_184000_slab4_phase2a_approval_cluster
-- Purpose:   Slab 4 Phase 2a — close Class A SECDEF pattern hole in the approval cluster.
--            Add `PERFORM set_config('rls.role','platform_admin',true)` to the top of 4
--            SECURITY DEFINER functions that operate on FORCE-RLS tables. Closes the
--            transitive risk surfaced by the Slab 7c BYPASSRLS removal (without this,
--            owner=jarvisbrain BYPASSRLS is the only thing keeping these functions
--            working).
-- Reference: docs/discovery/DISCOVERY_2026-05-11_slab4_phase1a_secdef_audit.md (§5 HIGH)
-- Functions: enqueue_approval_request, decide_approval, consume_approved_queue_item,
--            expire_pending_approvals.
-- Body diff: One inserted line at top of each function body; existing logic unchanged.
-- Verify:    Two-stage POST-FLIGHT in the same transaction —
--              (1) pg_get_functiondef introspection: each function body contains the
--                  expected set_config line.
--              (2) Functional smoke under jarvis_alpha_writer role, inside a savepoint
--                  that is rolled back so prod data is not mutated.

-- -------------------------------------------------------------------------
-- 1. enqueue_approval_request
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.enqueue_approval_request(p_action_classes text[], p_risk_tier text, p_actor_sub text, p_actor_type text, p_description text, p_parameters_hash text, p_nonce text)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    v_queue_id uuid;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    INSERT INTO public.alpha_approval_queue
      (action_class, risk_tier, actor_sub, actor_type, description,
       parameters_hash, nonce, status, requested_at, expires_at)
    VALUES
      (p_action_classes, p_risk_tier, p_actor_sub, p_actor_type, p_description,
       p_parameters_hash, p_nonce, 'pending', NOW(), NOW() + INTERVAL '10 minutes')
    RETURNING id INTO v_queue_id;

    INSERT INTO public.alpha_approval_audit
      (approval_id, action_class, risk_tier, actor_sub, actor_type,
       description, parameters_hash, nonce, decision, decided_by, overnight)
    VALUES
      (v_queue_id, p_action_classes, p_risk_tier, p_actor_sub, p_actor_type,
       p_description, p_parameters_hash, p_nonce, 'auto', p_actor_sub, false);

    RETURN v_queue_id;
END;
$function$;

-- -------------------------------------------------------------------------
-- 2. decide_approval
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.decide_approval(p_queue_id uuid, p_decision text, p_decided_by text, p_nonce text)
 RETURNS TABLE(queue_id uuid, action_class text[], risk_tier text, actor_sub text, actor_type text, description text, parameters_hash text, overnight boolean, expires_at timestamp with time zone)
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    v_row alpha_approval_queue%ROWTYPE;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    -- Fetch row
    SELECT * INTO v_row
    FROM alpha_approval_queue
    WHERE id = p_queue_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'APPROVAL_NOT_FOUND queue_id=%', p_queue_id
            USING ERRCODE = 'P0002';
    END IF;

    IF v_row.status <> 'pending' THEN
        RAISE EXCEPTION 'APPROVAL_ALREADY_DECIDED queue_id=% status=%', p_queue_id, v_row.status
            USING ERRCODE = 'P0003';
    END IF;

    IF p_decision NOT IN ('approved', 'denied') THEN
        RAISE EXCEPTION 'INVALID_DECISION value=%', p_decision
            USING ERRCODE = 'P0004';
    END IF;

    -- Update queue row
    IF p_decision = 'approved' THEN
        UPDATE alpha_approval_queue
        SET status     = 'approved',
            decided_by = p_decided_by,
            decided_at = NOW(),
            expires_at = NOW() + INTERVAL '10 minutes'
        WHERE id = p_queue_id;
    ELSE
        UPDATE alpha_approval_queue
        SET status     = 'denied',
            decided_by = p_decided_by,
            decided_at = NOW()
        WHERE id = p_queue_id;
    END IF;

    -- Write audit row
    INSERT INTO alpha_approval_audit (
        approval_id, action_class, risk_tier, actor_sub, actor_type,
        description, parameters_hash, nonce, decision, decided_by, overnight
    ) VALUES (
        v_row.id, v_row.action_class, v_row.risk_tier, v_row.actor_sub, v_row.actor_type,
        v_row.description, v_row.parameters_hash, p_nonce, p_decision, p_decided_by, v_row.overnight
    );

    -- Return updated row for Python to build response
    RETURN QUERY
    SELECT
        v_row.id,
        v_row.action_class,
        v_row.risk_tier,
        v_row.actor_sub,
        v_row.actor_type,
        v_row.description,
        v_row.parameters_hash,
        v_row.overnight,
        CASE WHEN p_decision = 'approved'
             THEN NOW() + INTERVAL '10 minutes'
             ELSE NULL::timestamptz
        END AS expires_at;
END;
$function$;

-- -------------------------------------------------------------------------
-- 3. consume_approved_queue_item
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.consume_approved_queue_item(p_queue_id uuid)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    UPDATE public.alpha_approval_queue
       SET status = 'executed',
           executed_at = NOW()
     WHERE id = p_queue_id;
END;
$function$;

-- -------------------------------------------------------------------------
-- 4. expire_pending_approvals
-- -------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.expire_pending_approvals()
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    v_count integer;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    -- Multi-row safe: chain UPDATE -> INSERT in a single CTE statement.
    -- Replaces an earlier pattern that raised P0003 (multi-row INTO scalar).
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

-- -------------------------------------------------------------------------
-- POST-FLIGHT 1: introspection — each function body contains the new set_config line.
-- Runs in the same transaction as the CREATEs above, so it sees the new definitions.
-- -------------------------------------------------------------------------
DO $$
DECLARE
    v_fn text;
    v_names text[] := ARRAY[
        'enqueue_approval_request',
        'decide_approval',
        'consume_approved_queue_item',
        'expire_pending_approvals'
    ];
BEGIN
    FOREACH v_fn IN ARRAY v_names LOOP
        IF NOT EXISTS (
            SELECT 1
              FROM pg_proc
             WHERE proname = v_fn
               AND pronamespace = 'public'::regnamespace
               AND pg_get_functiondef(oid) LIKE '%set_config(''rls.role'', ''platform_admin'', true)%'
        ) THEN
            RAISE EXCEPTION 'POST-FLIGHT introspect FAILED: % missing set_config line', v_fn;
        END IF;
        RAISE NOTICE 'POST-FLIGHT introspect: % contains rls.role set_config OK', v_fn;
    END LOOP;
END $$;

-- -------------------------------------------------------------------------
-- POST-FLIGHT 2: functional smoke under jarvis_alpha_writer role.
-- All work inside a savepoint that is ROLLBACKed, so no prod data is mutated.
-- -------------------------------------------------------------------------
SAVEPOINT verify_functional;

SET LOCAL ROLE jarvis_alpha_writer;

DO $$
DECLARE
    v_id uuid;
BEGIN
    -- expire_pending_approvals: zero-arg, read-mostly (only rewrites stale rows).
    BEGIN
        PERFORM public.expire_pending_approvals();
        RAISE NOTICE 'POST-FLIGHT functional: expire_pending_approvals OK under jarvis_alpha_writer';
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: expire_pending_approvals FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;

    -- consume_approved_queue_item: bogus UUID → UPDATE matches 0 rows, no error.
    BEGIN
        PERFORM public.consume_approved_queue_item('00000000-0000-0000-0000-000000000000'::uuid);
        RAISE NOTICE 'POST-FLIGHT functional: consume_approved_queue_item OK under jarvis_alpha_writer';
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: consume_approved_queue_item FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;

    -- decide_approval: bogus UUID → expected to raise APPROVAL_NOT_FOUND (P0002).
    -- Treat anything else as failure.
    BEGIN
        PERFORM public.decide_approval(
            '00000000-0000-0000-0000-000000000000'::uuid,
            'approved',
            'post-flight-test',
            'post-flight-nonce'
        );
        RAISE EXCEPTION 'POST-FLIGHT functional: decide_approval should have raised P0002 but returned';
    EXCEPTION
        WHEN sqlstate 'P0002' THEN
            RAISE NOTICE 'POST-FLIGHT functional: decide_approval OK under jarvis_alpha_writer (expected P0002)';
        WHEN OTHERS THEN
            RAISE EXCEPTION 'POST-FLIGHT functional: decide_approval FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;

    -- enqueue_approval_request: writes a row pair. Savepoint rollback discards it.
    BEGIN
        v_id := public.enqueue_approval_request(
            ARRAY['post_flight_verify']::text[],
            'tier_low',
            'post-flight-test-actor',
            'user',
            'POST-FLIGHT verification row — rolled back by savepoint',
            'sha256:post-flight-test',
            'post-flight-nonce-' || gen_random_uuid()::text
        );
        RAISE NOTICE 'POST-FLIGHT functional: enqueue_approval_request OK under jarvis_alpha_writer (queue_id=%)', v_id;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: enqueue_approval_request FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;
END $$;

RESET ROLE;

-- Roll back all writes + role + set_config side effects from the verification block.
ROLLBACK TO SAVEPOINT verify_functional;
