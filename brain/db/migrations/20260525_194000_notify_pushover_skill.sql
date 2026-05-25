-- Migration: 20260525_194000_notify_pushover_skill
-- Purpose:   Mark notify.send_pushover active and allow Buddy to use it
--            through SkillRunner/SkillPolicyGate.

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('notify.send_pushover', 'notify', 'send_pushover',
     'Send a Pushover notification to Ken through Gateway.', 'T2', 'notify.send', 'active',
     TRUE, FALSE, TRUE, '{"egress": "gateway", "provider": "pushover"}'::jsonb)
ON CONFLICT (skill_name) DO UPDATE
SET description = EXCLUDED.description,
    approval_tier = EXCLUDED.approval_tier,
    scope = EXCLUDED.scope,
    status = EXCLUDED.status,
    mutates_state = EXCLUDED.mutates_state,
    body_access = EXCLUDED.body_access,
    idempotency_required = EXCLUDED.idempotency_required,
    metadata = EXCLUDED.metadata,
    updated_at = NOW();

UPDATE public.alpha_agents
SET allowed_skills = CASE
        WHEN 'notify.send_pushover' = ANY(allowed_skills) THEN allowed_skills
        ELSE array_append(allowed_skills, 'notify.send_pushover')
    END,
    allowed_scopes = CASE
        WHEN 'notify.send' = ANY(allowed_scopes) THEN allowed_scopes
        ELSE array_append(allowed_scopes, 'notify.send')
    END,
    updated_at = NOW()
WHERE agent_id = 'buddy';

DO $$
DECLARE
    v_status text;
    v_buddy_can_notify boolean;
BEGIN
    SELECT status INTO v_status
      FROM public.alpha_skill_registry
     WHERE skill_name = 'notify.send_pushover';

    IF v_status IS DISTINCT FROM 'active' THEN
        RAISE EXCEPTION 'POST-FLIGHT notify.send_pushover FAILED: status=%', v_status;
    END IF;

    SELECT 'notify.send_pushover' = ANY(allowed_skills)
       AND 'notify.send' = ANY(allowed_scopes)
      INTO v_buddy_can_notify
      FROM public.alpha_agents
     WHERE agent_id = 'buddy';

    IF v_buddy_can_notify IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'POST-FLIGHT buddy notify policy FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT notify.send_pushover OK';
END $$;
