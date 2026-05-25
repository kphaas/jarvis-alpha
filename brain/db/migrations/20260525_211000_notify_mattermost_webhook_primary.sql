-- Migration: 20260525_211000_notify_mattermost_webhook_primary
-- Purpose:   Align Mattermost notification registry metadata with the
--            production Phase 1 decision: incoming webhooks are primary;
--            bot REST remains available for Phase 2+ automation.

UPDATE public.alpha_skill_registry
SET metadata = '{"primary": "mattermost", "delivery": "incoming_webhook", "fallback": "pushover"}'::jsonb,
    updated_at = NOW()
WHERE skill_name = 'notify.send';

UPDATE public.alpha_skill_registry
SET metadata = '{"egress": "gateway", "provider": "mattermost", "delivery": "incoming_webhook", "rest_api": "phase2"}'::jsonb,
    updated_at = NOW()
WHERE skill_name = 'notify.send_mattermost';

DO $$
DECLARE
    v_delivery text;
BEGIN
    SELECT metadata->>'delivery'
      INTO v_delivery
      FROM public.alpha_skill_registry
     WHERE skill_name = 'notify.send_mattermost';

    IF v_delivery IS DISTINCT FROM 'incoming_webhook' THEN
        RAISE EXCEPTION 'POST-FLIGHT Mattermost webhook metadata FAILED: delivery=%', v_delivery;
    END IF;

    RAISE NOTICE 'POST-FLIGHT Mattermost webhook primary metadata OK';
END $$;
