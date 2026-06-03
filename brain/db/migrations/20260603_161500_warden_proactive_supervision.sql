-- Migration: 20260603_161500_warden_proactive_supervision
-- Purpose: Enable scheduled Warden supervision metadata.

UPDATE public.alpha_agents
SET metadata = metadata || '{
      "supervision_interval_seconds": 600,
      "supervision_mode": "scheduled_debounce_on_change",
      "supervision_channel_key": "security_alerts"
    }'::jsonb,
    updated_at = NOW()
WHERE agent_id = 'warden';

DO $$
DECLARE
    v_interval integer;
    v_mode text;
BEGIN
    SELECT (metadata->>'supervision_interval_seconds')::integer,
           metadata->>'supervision_mode'
      INTO v_interval, v_mode
    FROM public.alpha_agents
    WHERE agent_id = 'warden';

    IF v_interval IS DISTINCT FROM 600
       OR v_mode IS DISTINCT FROM 'scheduled_debounce_on_change' THEN
        RAISE EXCEPTION 'POST-FLIGHT Warden proactive supervision metadata FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Warden proactive supervision metadata OK';
END $$;
