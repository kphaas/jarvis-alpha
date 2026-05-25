-- Migration: 20260525_204000_notify_mattermost_skill
-- Purpose:   Add Mattermost as Alpha's primary ChatOps notification surface
--            while retaining Pushover as the fallback wake-up channel.

INSERT INTO public.alpha_skill_registry
    (skill_name, domain, action, description, approval_tier, scope, status,
     mutates_state, body_access, idempotency_required, metadata)
VALUES
    ('notify.send', 'notify', 'send',
     'Send an Alpha notification through the primary ChatOps channel.',
     'T2', 'notify.send', 'active',
     TRUE, FALSE, TRUE,
     '{"primary": "mattermost", "fallback": "pushover"}'::jsonb),
    ('notify.send_mattermost', 'notify', 'send_mattermost',
     'Send a Mattermost ChatOps notification through Gateway.',
     'T2', 'notify.send', 'active',
     TRUE, FALSE, TRUE,
     '{"egress": "gateway", "provider": "mattermost"}'::jsonb),
    ('notify.send_pushover', 'notify', 'send_pushover',
     'Send a fallback Pushover notification to Ken through Gateway.',
     'T2', 'notify.send', 'active',
     TRUE, FALSE, TRUE,
     '{"egress": "gateway", "provider": "pushover", "role": "fallback"}'::jsonb)
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
SET allowed_skills = ARRAY(
        SELECT DISTINCT skill_name
          FROM unnest(
            allowed_skills
            || ARRAY['notify.send', 'notify.send_mattermost', 'notify.send_pushover']
          ) AS t(skill_name)
    ),
    allowed_scopes = ARRAY(
        SELECT DISTINCT scope_name
          FROM unnest(allowed_scopes || ARRAY['notify.send']) AS t(scope_name)
    ),
    updated_at = NOW()
WHERE agent_id = 'buddy';

DO $$
DECLARE
    v_active_count integer;
    v_buddy_can_notify boolean;
BEGIN
    SELECT COUNT(*) INTO v_active_count
      FROM public.alpha_skill_registry
     WHERE skill_name IN ('notify.send', 'notify.send_mattermost', 'notify.send_pushover')
       AND status = 'active'
       AND scope = 'notify.send'
       AND mutates_state IS TRUE
       AND idempotency_required IS TRUE;

    IF v_active_count != 3 THEN
        RAISE EXCEPTION 'POST-FLIGHT Mattermost notify skills FAILED: active_count=%', v_active_count;
    END IF;

    SELECT ARRAY['notify.send', 'notify.send_mattermost', 'notify.send_pushover']
           <@ allowed_skills
       AND 'notify.send' = ANY(allowed_scopes)
      INTO v_buddy_can_notify
      FROM public.alpha_agents
     WHERE agent_id = 'buddy';

    IF v_buddy_can_notify IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'POST-FLIGHT buddy Mattermost notify policy FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT notify.send Mattermost primary OK';
END $$;
