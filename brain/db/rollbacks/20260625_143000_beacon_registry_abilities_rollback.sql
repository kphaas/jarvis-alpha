-- Rollback: 20260625_143000_beacon_registry_abilities
-- Purpose:  Restore Beacon search skill manifests to the previous search-only
--           registry source set.

UPDATE public.alpha_skill_registry
   SET metadata = jsonb_set(
           metadata - 'source_selection' - 'on_hold_data_source_ids' - 'spend_guard',
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
           = '["brave-search", "perplexity-search"]'::jsonb
       AND NOT metadata ? 'source_selection'
       AND NOT metadata ? 'on_hold_data_source_ids'
       AND NOT metadata ? 'spend_guard';

    IF v_skill_count <> 2 THEN
        RAISE EXCEPTION 'POST-ROLLBACK Beacon registry abilities restore FAILED: count=%', v_skill_count;
    END IF;

    RAISE NOTICE 'POST-ROLLBACK Beacon registry abilities restore OK';
END $$;
