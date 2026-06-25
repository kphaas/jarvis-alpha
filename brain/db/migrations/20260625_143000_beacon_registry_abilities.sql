-- Migration: 20260625_143000_beacon_registry_abilities
-- Purpose:   Link Beacon search skills to the expanded approved registry source set.

UPDATE public.alpha_skill_registry
   SET metadata = jsonb_set(
           jsonb_set(
             jsonb_set(
               jsonb_set(
                 metadata,
                 '{manifest,egress,data_source_ids}',
                 '[
                    "brave-search",
                    "perplexity-search",
                    "tavily-search",
                    "pubmed-eutils",
                    "sec-edgar",
                    "osv-dev",
                    "cisa-kev",
                    "openalex",
                    "google-workspace",
                    "microsoft-graph"
                  ]'::jsonb,
                 true
               ),
               '{source_selection}',
               to_jsonb('registry_backed'::text),
               true
             ),
             '{on_hold_data_source_ids}',
             '["quiverquant"]'::jsonb,
             true
           ),
           '{spend_guard}',
           to_jsonb('gateway_provider_allowlist_and_budget_limits'::text),
           true
       ),
       updated_at = NOW()
 WHERE skill_name IN ('internet_scout.search', 'internet_scout.deep_research')
   AND metadata->'manifest'->'egress'->>'provider' = 'beacon';

DO $$
DECLARE
    v_skill_count integer;
    v_on_hold_count integer;
BEGIN
    SELECT COUNT(*)
      INTO v_skill_count
      FROM public.alpha_skill_registry
     WHERE skill_name IN ('internet_scout.search', 'internet_scout.deep_research')
       AND metadata->'manifest'->'egress'->>'provider' = 'beacon'
       AND metadata->'manifest'->'egress'->'data_source_ids'
           = '[
                "brave-search",
                "perplexity-search",
                "tavily-search",
                "pubmed-eutils",
                "sec-edgar",
                "osv-dev",
                "cisa-kev",
                "openalex",
                "google-workspace",
                "microsoft-graph"
              ]'::jsonb
       AND metadata->>'source_selection' = 'registry_backed'
       AND metadata->>'spend_guard' = 'gateway_provider_allowlist_and_budget_limits';

    SELECT COUNT(*)
      INTO v_on_hold_count
      FROM public.alpha_skill_registry
     WHERE skill_name IN ('internet_scout.search', 'internet_scout.deep_research')
       AND metadata->'manifest'->'egress'->'data_source_ids' ? 'quiverquant';

    IF v_skill_count <> 2 THEN
        RAISE EXCEPTION 'POST-FLIGHT Beacon registry abilities link FAILED: count=%', v_skill_count;
    END IF;

    IF v_on_hold_count <> 0 THEN
        RAISE EXCEPTION 'POST-FLIGHT Beacon registry abilities on-hold guard FAILED: count=%', v_on_hold_count;
    END IF;

    RAISE NOTICE 'POST-FLIGHT Beacon registry abilities link OK';
END $$;
