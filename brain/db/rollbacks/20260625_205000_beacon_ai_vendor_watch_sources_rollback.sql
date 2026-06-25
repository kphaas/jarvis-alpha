-- Rollback: 20260625_205000_beacon_ai_vendor_watch_sources
-- Purpose:  Restore Beacon search skill manifests to the prior approved
--           non-AI-vendor registry source set.

UPDATE public.alpha_skill_registry
   SET metadata = jsonb_set(
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
       updated_at = NOW()
 WHERE skill_name IN ('internet_scout.search', 'internet_scout.deep_research')
   AND metadata->'manifest'->'egress'->>'provider' = 'beacon'
   AND metadata->>'source_selection' = 'registry_backed';

DO $$
DECLARE
    v_skill_count integer;
    v_ai_vendor_count integer;
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
       AND metadata->>'source_selection' = 'registry_backed';

    SELECT COUNT(*)
      INTO v_ai_vendor_count
      FROM public.alpha_skill_registry
     WHERE skill_name IN ('internet_scout.search', 'internet_scout.deep_research')
       AND (
            metadata->'manifest'->'egress'->'data_source_ids' ? 'openai-news-rss'
         OR metadata->'manifest'->'egress'->'data_source_ids' ? 'openai-api-changelog'
         OR metadata->'manifest'->'egress'->'data_source_ids' ? 'aws-whats-new-ai'
         OR metadata->'manifest'->'egress'->'data_source_ids' ? 'azure-ai-blog'
         OR metadata->'manifest'->'egress'->'data_source_ids' ? 'github-copilot-changelog'
         OR metadata->'manifest'->'egress'->'data_source_ids' ? 'ai-vendor-status-feeds'
       );

    IF v_skill_count <> 2 THEN
        RAISE EXCEPTION 'POST-ROLLBACK Beacon AI vendor watch source restore FAILED: count=%', v_skill_count;
    END IF;

    IF v_ai_vendor_count <> 0 THEN
        RAISE EXCEPTION 'POST-ROLLBACK Beacon AI vendor watch source removal FAILED: count=%', v_ai_vendor_count;
    END IF;

    RAISE NOTICE 'POST-ROLLBACK Beacon AI vendor watch source restore OK';
END $$;
