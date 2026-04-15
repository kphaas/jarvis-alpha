-- Migration: 20260415_100000_decide_approval_secdef
-- Purpose: SECURITY DEFINER wrapper for approval decide + audit write
-- Called by: routes/approvals.py /decide handler

BEGIN;

CREATE OR REPLACE FUNCTION decide_approval(
    p_queue_id    uuid,
    p_decision    text,
    p_decided_by  text,
    p_nonce       text
)
RETURNS TABLE (
    queue_id     uuid,
    action_class text[],
    risk_tier    text,
    actor_sub    text,
    actor_type   text,
    description  text,
    parameters_hash text,
    overnight    boolean,
    expires_at   timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_row alpha_approval_queue%ROWTYPE;
BEGIN
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
$$;

COMMIT;
