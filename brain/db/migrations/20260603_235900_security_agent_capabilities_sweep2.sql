-- Migration: 20260603_235900_security_agent_capabilities_sweep2
-- Purpose:   Promote Tripwire enrichment/clustering and Warden routing/briefing
--            capabilities without granting new remediation powers.

UPDATE public.alpha_agents
SET metadata = jsonb_set(
    jsonb_set(
      metadata,
      '{capabilities}',
      (
        SELECT jsonb_agg(DISTINCT item)
        FROM jsonb_array_elements_text(
          COALESCE(metadata->'capabilities', '[]'::jsonb) ||
          '[
            "source_reputation_enrichment",
            "repeated_probe_clustering"
          ]'::jsonb
        ) AS t(item)
      ),
      true
    ),
    '{monitors}',
    (
      SELECT jsonb_agg(DISTINCT item)
      FROM jsonb_array_elements_text(
        COALESCE(metadata->'monitors', '[]'::jsonb) ||
        '[
          "honeypot_hits",
          "trap_paths",
          "source_patterns",
          "source_reputation",
          "probe_clusters"
        ]'::jsonb
      ) AS t(item)
    ),
    true
)
WHERE agent_id = 'tripwire';

UPDATE public.alpha_agents
SET metadata = jsonb_set(
    jsonb_set(
      metadata,
      '{capabilities}',
      (
        SELECT jsonb_agg(DISTINCT item)
        FROM jsonb_array_elements_text(
          COALESCE(metadata->'capabilities', '[]'::jsonb) ||
          '[
            "weekly_security_brief",
            "owner_routing",
            "auto_ticket_candidates"
          ]'::jsonb
        ) AS t(item)
      ),
      true
    ),
    '{active_security_capabilities}',
    (
      SELECT jsonb_agg(DISTINCT item)
      FROM jsonb_array_elements_text(
        COALESCE(metadata->'active_security_capabilities', '[]'::jsonb) ||
        '[
          "tripwire_source_reputation_enrichment",
          "tripwire_repeated_probe_clustering",
          "warden_weekly_security_brief",
          "warden_owner_routing",
          "warden_auto_ticket_candidates"
        ]'::jsonb
      ) AS t(item)
    ),
    true
)
WHERE agent_id = 'warden';

DO $$
DECLARE
    v_tripwire jsonb;
    v_warden jsonb;
BEGIN
    SELECT metadata INTO v_tripwire
    FROM public.alpha_agents
    WHERE agent_id = 'tripwire';

    SELECT metadata INTO v_warden
    FROM public.alpha_agents
    WHERE agent_id = 'warden';

    IF NOT (v_tripwire->'capabilities' ? 'source_reputation_enrichment')
       OR NOT (v_tripwire->'capabilities' ? 'repeated_probe_clustering')
       OR NOT (v_warden->'capabilities' ? 'weekly_security_brief')
       OR NOT (v_warden->'capabilities' ? 'owner_routing')
       OR NOT (v_warden->'active_security_capabilities' ? 'warden_auto_ticket_candidates') THEN
        RAISE EXCEPTION 'POST-FLIGHT security agent capability sweep2 FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT security agent capability sweep2 OK';
END $$;
