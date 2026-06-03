-- Enable Sweep now that repeated network findings are debounced by state.

UPDATE public.alpha_agents
SET enabled = TRUE,
    metadata = metadata
      || '{
        "enabled_reason": "unifi_tls_pin_monitoring",
        "alert_debounce": "state_change"
      }'::jsonb
WHERE agent_id = 'network_watchdog';

DO $$
DECLARE
    v_enabled boolean;
    v_debounce text;
BEGIN
    SELECT enabled, metadata->>'alert_debounce'
      INTO v_enabled, v_debounce
    FROM public.alpha_agents
    WHERE agent_id = 'network_watchdog';

    IF v_enabled IS DISTINCT FROM TRUE
       OR v_debounce IS DISTINCT FROM 'state_change' THEN
        RAISE EXCEPTION 'POST-FLIGHT Sweep enablement FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Sweep enablement OK';
END $$;
