-- Migration: 20260602_102500_keyturner_skillrunner_bridge
-- Purpose:   Mark Keyturner's rotate skill as a SkillRunner skill protected by
--            the T4 approval queue bridge.

UPDATE public.alpha_skill_registry
SET metadata = metadata
    || jsonb_build_object(
        'execution_path', 'skill_runner',
        'approval_queue_bridge', 'enabled',
        'actuator', 'gateway_rotation_proxy'
    ),
    updated_at = NOW()
WHERE skill_name = 'secrets.rotate';

DO $$
DECLARE
    v_bridge_enabled boolean;
BEGIN
    SELECT metadata->>'execution_path' = 'skill_runner'
       AND metadata->>'approval_queue_bridge' = 'enabled'
    INTO v_bridge_enabled
    FROM public.alpha_skill_registry
    WHERE skill_name = 'secrets.rotate'
      AND status = 'active'
      AND approval_tier = 'T4';

    IF COALESCE(v_bridge_enabled, false) IS NOT TRUE THEN
        RAISE EXCEPTION 'POST-FLIGHT Keyturner SkillRunner bridge FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Keyturner SkillRunner bridge OK';
END $$;
