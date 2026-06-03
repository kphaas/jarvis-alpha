-- Migration: 20260603_223000_security_agent_capabilities_sweep1
-- Purpose:   Surface the first security-agent capability sweep in Warden/Sweep
--            metadata without granting new write powers.

UPDATE public.alpha_agents
SET metadata = jsonb_set(
    jsonb_set(
      metadata,
      '{monitors}',
      (
        SELECT jsonb_agg(DISTINCT item)
        FROM jsonb_array_elements_text(
          COALESCE(metadata->'monitors', '[]'::jsonb) ||
          '[
            "service_tls_certs",
            "unifi_tls_pin",
            "wan_health",
            "new_clients",
            "unknown_device_quarantine",
            "unifi_firmware_drift",
            "wan_failover_health"
          ]'::jsonb
        ) AS t(item)
      ),
      true
    ),
    '{active_network_checks}',
    '[
      "unifi.quarantine_recommendation",
      "unifi.firmware_drift",
      "unifi.wan_failover_health"
    ]'::jsonb,
    true
)
WHERE agent_id = 'sweep';

UPDATE public.alpha_agents
SET metadata = jsonb_set(
    jsonb_set(
      metadata,
      '{active_security_capabilities}',
      (
        SELECT jsonb_agg(DISTINCT item)
        FROM jsonb_array_elements_text(
          COALESCE(metadata->'active_security_capabilities', '[]'::jsonb) ||
          '[
            "porchlight_dependency_cve_scan",
            "porchlight_github_branch_protection_drift",
            "keyturner_oauth_health",
            "keyturner_rotation_dry_run",
            "keyturner_secrets_forecast",
            "sweep_unknown_device_quarantine",
            "sweep_unifi_firmware_drift",
            "sweep_wan_failover_health"
          ]'::jsonb
        ) AS t(item)
      ),
      true
    ),
    '{active_network_hardening}',
    '"network_observability_sweep1"'::jsonb,
    true
)
WHERE agent_id = 'warden';

DO $$
DECLARE
    v_sweep jsonb;
    v_warden jsonb;
BEGIN
    SELECT metadata INTO v_sweep
    FROM public.alpha_agents
    WHERE agent_id = 'sweep';

    SELECT metadata INTO v_warden
    FROM public.alpha_agents
    WHERE agent_id = 'warden';

    IF NOT (v_sweep->'monitors' ? 'unknown_device_quarantine')
       OR NOT (v_sweep->'monitors' ? 'unifi_firmware_drift')
       OR NOT (v_sweep->'monitors' ? 'wan_failover_health')
       OR NOT (v_warden->'active_security_capabilities' ? 'keyturner_oauth_health') THEN
        RAISE EXCEPTION 'POST-FLIGHT security agent capability sweep1 FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT security agent capability sweep1 OK';
END $$;
