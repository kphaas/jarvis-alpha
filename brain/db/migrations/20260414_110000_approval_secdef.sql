-- Stage 7: SECURITY DEFINER wrapper for approval expiry
-- Wraps buddy_agent bare DML on alpha_approval_queue + alpha_approval_audit
-- Must be called inside a transaction by the caller

BEGIN;

CREATE OR REPLACE FUNCTION public.expire_pending_approvals()
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
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
$$;

REVOKE ALL ON FUNCTION public.expire_pending_approvals() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.expire_pending_approvals() TO jarvis_alpha_app;
GRANT EXECUTE ON FUNCTION public.expire_pending_approvals() TO jarvis_alpha_writer;

COMMIT;
