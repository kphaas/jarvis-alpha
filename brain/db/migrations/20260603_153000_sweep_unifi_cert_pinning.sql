-- Mark Sweep as the active owner/monitor for UniFi TLS certificate pinning.

UPDATE public.alpha_agents
SET metadata = metadata
    || '{
      "active_network_hardening": "unifi_cert_pinning",
      "remediation_policy": {
        "T1": "delegate_low_risk_checks",
        "T4_T5": "route_to_owner_with_approval"
      }
    }'::jsonb
WHERE agent_id = 'warden';

UPDATE public.alpha_agents
SET metadata = (metadata - 'next_hardening')
    || '{
      "active_hardening": "unifi_cert_pinning",
      "monitors": ["unifi_tls_pin", "wan_health", "new_clients"]
    }'::jsonb
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

    IF v_warden->>'active_network_hardening' != 'unifi_cert_pinning'
       OR v_sweep->>'active_hardening' != 'unifi_cert_pinning'
       OR NOT (v_sweep->'monitors' ? 'unifi_tls_pin') THEN
        RAISE EXCEPTION 'POST-FLIGHT Sweep UniFi cert pinning metadata FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Sweep UniFi cert pinning metadata OK';
END $$;
