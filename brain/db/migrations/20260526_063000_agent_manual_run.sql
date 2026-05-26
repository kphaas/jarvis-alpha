-- Migration: 20260526_063000_agent_manual_run
-- Purpose:   Opt in low-risk agents to explicit manual Run Now control.

UPDATE public.alpha_agents
SET metadata = metadata || '{"manual_run_enabled": true}'::jsonb,
    updated_at = NOW()
WHERE agent_id IN ('chatops_smoke', 'network_watchdog');

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.alpha_agents
        WHERE agent_id = 'chatops_smoke'
          AND metadata->>'manual_run_enabled' = 'true'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT chatops_smoke manual_run_enabled FAILED';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.alpha_agents
        WHERE agent_id = 'network_watchdog'
          AND metadata->>'manual_run_enabled' = 'true'
          AND enabled = FALSE
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT network_watchdog manual metadata/disabled posture FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT agent manual run metadata OK';
END $$;
