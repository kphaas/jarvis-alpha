-- Migration: 20260603_181000_sweep_tls_cert_renewal
-- Purpose: Make Sweep the Warden-managed owner for service TLS cert renewal.

UPDATE public.alpha_agents
SET metadata = metadata
    || jsonb_build_object(
        'active_network_hardening', 'service_tls_cert_renewal',
        'next_network_hardening', 'service_tls_cert_renewal'
    )
WHERE agent_id = 'warden';

UPDATE public.alpha_agents
SET metadata = metadata
    || jsonb_build_object(
        'active_hardening', 'service_tls_cert_renewal',
        'completed_hardenings', jsonb_build_array('unifi_cert_pinning'),
        'cert_renewal', jsonb_build_object(
            'script', 'scripts/sweep_tls_cert_renewal.py',
            'launch_label', 'com.jarvis.alpha.sweep-cert-renewal',
            'threshold_days', 30
        ),
        'monitors', jsonb_build_array(
            'service_tls_certs',
            'unifi_tls_pin',
            'wan_health',
            'new_clients'
        )
    )
WHERE agent_id = 'network_watchdog';

DO $$
DECLARE
    v_warden jsonb;
    v_sweep jsonb;
BEGIN
    SELECT metadata INTO v_warden
    FROM public.alpha_agents
    WHERE agent_id = 'warden';

    SELECT metadata INTO v_sweep
    FROM public.alpha_agents
    WHERE agent_id = 'network_watchdog';

    IF v_warden->>'active_network_hardening' != 'service_tls_cert_renewal'
       OR v_sweep->>'active_hardening' != 'service_tls_cert_renewal'
       OR v_sweep #>> '{cert_renewal,launch_label}' != 'com.jarvis.alpha.sweep-cert-renewal'
       OR NOT (v_sweep->'monitors' ? 'service_tls_certs') THEN
        RAISE EXCEPTION 'POST-FLIGHT Sweep TLS cert renewal metadata FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Sweep TLS cert renewal metadata OK';
END $$;
