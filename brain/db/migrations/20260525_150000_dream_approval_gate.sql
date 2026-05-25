-- Migration: 20260525_150000_dream_approval_gate
-- Purpose:   Dream Mode write-capable execution gate.
--            Queue autonomous Dream side-effecting steps as overnight approval
--            requests with explicit preview metadata before any execution.

CREATE OR REPLACE FUNCTION public.enqueue_dream_step_approval_request(
    p_action_classes text[],
    p_risk_tier text,
    p_actor_sub text,
    p_actor_type text,
    p_description text,
    p_parameters_hash text,
    p_parameters_preview text,
    p_nonce text
)
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
       parameters_hash, parameters_preview, nonce, status, requested_at,
       expires_at, overnight)
    VALUES
      (p_action_classes, p_risk_tier, p_actor_sub, p_actor_type, p_description,
       p_parameters_hash, p_parameters_preview, p_nonce, 'pending', NOW(),
       NOW() + INTERVAL '12 hours', TRUE)
    RETURNING id INTO v_queue_id;

    INSERT INTO public.alpha_approval_audit
      (approval_id, action_class, risk_tier, actor_sub, actor_type,
       description, parameters_hash, nonce, decision, decided_by, overnight)
    VALUES
      (v_queue_id, p_action_classes, p_risk_tier, p_actor_sub, p_actor_type,
       p_description, p_parameters_hash, p_nonce, 'auto', p_actor_sub, TRUE);

    RETURN v_queue_id;
END;
$function$;

COMMENT ON FUNCTION public.enqueue_dream_step_approval_request IS
'Queues Dream Mode write-capable steps as overnight approval requests before side effects. TD-122.';

REVOKE EXECUTE ON FUNCTION public.enqueue_dream_step_approval_request(
    text[], text, text, text, text, text, text, text
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.enqueue_dream_step_approval_request(
    text[], text, text, text, text, text, text, text
) TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.enqueue_dream_step_approval_request(
    text[], text, text, text, text, text, text, text
) TO jarvis_alpha_app;
GRANT EXECUTE ON FUNCTION public.enqueue_dream_step_approval_request(
    text[], text, text, text, text, text, text, text
) TO jarvisbrain;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_proc
         WHERE proname = 'enqueue_dream_step_approval_request'
           AND pronamespace = 'public'::regnamespace
           AND prosecdef = true
           AND pg_get_functiondef(oid) LIKE '%set_config(''rls.role'', ''platform_admin'', true)%'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT introspect FAILED: enqueue_dream_step_approval_request missing SECDEF or set_config';
    END IF;
    RAISE NOTICE 'POST-FLIGHT introspect: enqueue_dream_step_approval_request SECDEF OK';
END $$;

SAVEPOINT verify_functional;

SET LOCAL ROLE jarvis_alpha_writer;

DO $$
DECLARE
    v_id uuid;
BEGIN
    BEGIN
        v_id := public.enqueue_dream_step_approval_request(
            ARRAY['write', 'dream_autonomous'],
            'T4',
            'dream_mode',
            'agent',
            'POST-FLIGHT Dream approval gate smoke',
            md5('dream-gate-smoke-' || txid_current()::text || random()::text),
            '{"smoke":true}',
            md5(random()::text || clock_timestamp()::text)
        );
        RAISE NOTICE 'POST-FLIGHT functional: enqueue_dream_step_approval_request OK (id=%)', v_id;
    EXCEPTION WHEN OTHERS THEN
        RAISE EXCEPTION 'POST-FLIGHT functional: enqueue_dream_step_approval_request FAILED: % (SQLSTATE=%)', SQLERRM, SQLSTATE;
    END;
END $$;

RESET ROLE;

ROLLBACK TO SAVEPOINT verify_functional;
