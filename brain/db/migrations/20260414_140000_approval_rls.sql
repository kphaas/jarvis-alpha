-- Stage 6b: RLS on approval tables + SECDEF wrappers for middleware bare DML.
--
-- ENABLE (not FORCE) — FORCE RLS is Stage 6d.
-- Policies gate on jarvis.role = 'platform_admin' (set by brain/db/rls.py).
-- Route handlers (approvals.py) use rls_connection() which sets the GUC.
-- ApprovalMiddleware runs before rls_connection and must use SECDEF wrappers.

BEGIN;

-- 1. Enable RLS + admin-only policies -------------------------------

ALTER TABLE public.alpha_approval_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_approval_audit ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS approval_queue_isolation ON public.alpha_approval_queue;
CREATE POLICY approval_queue_isolation ON public.alpha_approval_queue
    FOR ALL
    USING (current_setting('jarvis.role', true) = 'platform_admin')
    WITH CHECK (current_setting('jarvis.role', true) = 'platform_admin');

DROP POLICY IF EXISTS approval_audit_isolation ON public.alpha_approval_audit;
CREATE POLICY approval_audit_isolation ON public.alpha_approval_audit
    FOR ALL
    USING (current_setting('jarvis.role', true) = 'platform_admin')
    WITH CHECK (current_setting('jarvis.role', true) = 'platform_admin');

-- 2. SECDEF: enqueue a new T4/T5 approval request -------------------
-- Called by ApprovalMiddleware._queue_for_approval (runs pre-auth-ctx,
-- cannot use rls_connection). Atomic INSERT into queue + audit.

CREATE OR REPLACE FUNCTION public.enqueue_approval_request(
    p_action_classes   text[],
    p_risk_tier        text,
    p_actor_sub        text,
    p_actor_type       text,
    p_description      text,
    p_parameters_hash  text,
    p_nonce            text
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_queue_id uuid;
BEGIN
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
$$;

-- 3. SECDEF: mark an already-approved queue item as executed --------
-- Called by ApprovalMiddleware._consume_approved_queue on the pass-through
-- path. Single-row UPDATE, no audit row (consumption is not a decision).

CREATE OR REPLACE FUNCTION public.consume_approved_queue_item(
    p_queue_id uuid
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    UPDATE public.alpha_approval_queue
       SET status = 'executed',
           executed_at = NOW()
     WHERE id = p_queue_id;
END;
$$;

-- 4. Grants ---------------------------------------------------------

REVOKE ALL ON FUNCTION public.enqueue_approval_request(
    text[], text, text, text, text, text, text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.enqueue_approval_request(
    text[], text, text, text, text, text, text
) TO jarvis_alpha_app;
GRANT EXECUTE ON FUNCTION public.enqueue_approval_request(
    text[], text, text, text, text, text, text
) TO jarvis_alpha_writer;

REVOKE ALL ON FUNCTION public.consume_approved_queue_item(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.consume_approved_queue_item(uuid) TO jarvis_alpha_app;
GRANT EXECUTE ON FUNCTION public.consume_approved_queue_item(uuid) TO jarvis_alpha_writer;

COMMIT;
