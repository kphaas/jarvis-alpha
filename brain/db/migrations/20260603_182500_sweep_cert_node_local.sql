-- Migration: 20260603_182500_sweep_cert_node_local
-- Purpose: Mark Sweep TLS renewal as node-local instead of Brain SSH fan-out.

UPDATE public.alpha_agents
SET metadata = metadata
    || jsonb_build_object(
        'cert_renewal', jsonb_build_object(
            'script', 'scripts/sweep_tls_cert_renewal.py',
            'launch_label', 'com.jarvis.alpha.sweep-cert-renewal.*',
            'threshold_days', 30,
            'mode', 'node_local'
        )
    )
WHERE agent_id = 'network_watchdog';

DO $$
DECLARE
    v_sweep jsonb;
BEGIN
    SELECT metadata INTO v_sweep
    FROM public.alpha_agents
    WHERE agent_id = 'network_watchdog';

    IF v_sweep #>> '{cert_renewal,launch_label}' != 'com.jarvis.alpha.sweep-cert-renewal.*'
       OR v_sweep #>> '{cert_renewal,mode}' != 'node_local' THEN
        RAISE EXCEPTION 'POST-FLIGHT Sweep node-local TLS cert metadata FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Sweep node-local TLS cert metadata OK';
END $$;
