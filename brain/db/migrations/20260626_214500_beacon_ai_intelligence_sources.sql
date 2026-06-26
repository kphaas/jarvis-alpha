-- Migration: 20260626_214500_beacon_ai_intelligence_sources
-- Purpose:   Link Beacon skills to the expanded free AI intelligence source set.

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
              "arxiv-api",
              "semantic-scholar-api",
              "google-workspace",
              "microsoft-graph",
              "openai-news-rss",
              "openai-api-changelog",
              "aws-whats-new-ai",
              "azure-ai-blog",
              "github-copilot-changelog",
              "ai-vendor-status-feeds",
              "anthropic-api-release-notes",
              "google-gemini-api-changelog",
              "huggingface-hub-api",
              "github-releases-api"
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
                "arxiv-api",
                "semantic-scholar-api",
                "google-workspace",
                "microsoft-graph",
                "openai-news-rss",
                "openai-api-changelog",
                "aws-whats-new-ai",
                "azure-ai-blog",
                "github-copilot-changelog",
                "ai-vendor-status-feeds",
                "anthropic-api-release-notes",
                "google-gemini-api-changelog",
                "huggingface-hub-api",
                "github-releases-api"
              ]'::jsonb
       AND metadata->>'source_selection' = 'registry_backed'
       AND metadata->>'spend_guard' = 'gateway_provider_allowlist_and_budget_limits';

    SELECT COUNT(*)
      INTO v_on_hold_count
      FROM public.alpha_skill_registry
     WHERE skill_name IN ('internet_scout.search', 'internet_scout.deep_research')
       AND metadata->'manifest'->'egress'->'data_source_ids' ? 'quiverquant';

    IF v_skill_count <> 2 THEN
        RAISE EXCEPTION 'POST-FLIGHT Beacon AI intelligence source link FAILED: count=%', v_skill_count;
    END IF;

    IF v_on_hold_count <> 0 THEN
        RAISE EXCEPTION 'POST-FLIGHT Beacon AI intelligence on-hold guard FAILED: count=%', v_on_hold_count;
    END IF;

    RAISE NOTICE 'POST-FLIGHT Beacon AI intelligence source link OK';
END $$;
