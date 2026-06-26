-- Rollback: 20260626_214500_beacon_ai_intelligence_sources
-- Purpose:  Restore Beacon skill manifests to the prior AI vendor watch source set.

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
              "microsoft-graph",
              "openai-news-rss",
              "openai-api-changelog",
              "aws-whats-new-ai",
              "azure-ai-blog",
              "github-copilot-changelog",
              "ai-vendor-status-feeds"
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
    v_expanded_count integer;
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
                "microsoft-graph",
                "openai-news-rss",
                "openai-api-changelog",
                "aws-whats-new-ai",
                "azure-ai-blog",
                "github-copilot-changelog",
                "ai-vendor-status-feeds"
              ]'::jsonb
       AND metadata->>'source_selection' = 'registry_backed';

    SELECT COUNT(*)
      INTO v_expanded_count
      FROM public.alpha_skill_registry
     WHERE skill_name IN ('internet_scout.search', 'internet_scout.deep_research')
       AND (
            metadata->'manifest'->'egress'->'data_source_ids' ? 'arxiv-api'
         OR metadata->'manifest'->'egress'->'data_source_ids' ? 'semantic-scholar-api'
         OR metadata->'manifest'->'egress'->'data_source_ids' ? 'anthropic-api-release-notes'
         OR metadata->'manifest'->'egress'->'data_source_ids' ? 'google-gemini-api-changelog'
         OR metadata->'manifest'->'egress'->'data_source_ids' ? 'huggingface-hub-api'
         OR metadata->'manifest'->'egress'->'data_source_ids' ? 'github-releases-api'
       );

    IF v_skill_count <> 2 THEN
        RAISE EXCEPTION 'POST-ROLLBACK Beacon AI intelligence source restore FAILED: count=%', v_skill_count;
    END IF;

    IF v_expanded_count <> 0 THEN
        RAISE EXCEPTION 'POST-ROLLBACK Beacon AI intelligence source removal FAILED: count=%', v_expanded_count;
    END IF;

    RAISE NOTICE 'POST-ROLLBACK Beacon AI intelligence source restore OK';
END $$;
