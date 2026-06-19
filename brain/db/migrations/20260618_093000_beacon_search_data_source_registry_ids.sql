-- Migration: 20260618_093000_beacon_search_data_source_registry_ids
-- Purpose:   Link Beacon search skills to vendored jarvis-data-sources entries.

UPDATE public.alpha_skill_registry
   SET metadata = jsonb_set(
           metadata,
           '{manifest,egress,data_source_ids}',
           '["brave-search", "perplexity-search"]'::jsonb,
           true
       ),
       updated_at = NOW()
 WHERE skill_name IN ('internet_scout.search', 'internet_scout.deep_research')
   AND metadata->'manifest'->'egress'->>'provider' = 'beacon';

DO $$
DECLARE
    v_skill_count integer;
BEGIN
    SELECT COUNT(*)
      INTO v_skill_count
      FROM public.alpha_skill_registry
     WHERE skill_name IN ('internet_scout.search', 'internet_scout.deep_research')
       AND metadata->'manifest'->'egress'->>'provider' = 'beacon'
       AND metadata->'manifest'->'egress'->'data_source_ids'
           = '["brave-search", "perplexity-search"]'::jsonb;

    IF v_skill_count <> 2 THEN
        RAISE EXCEPTION 'POST-FLIGHT Beacon search data source link FAILED: count=%', v_skill_count;
    END IF;

    RAISE NOTICE 'POST-FLIGHT Beacon search data source link OK';
END $$;
