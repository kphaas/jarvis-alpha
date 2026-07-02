-- Rollback: 20260702_151500_skill_discovery_mapping
-- Remove only discovery metadata seeded by this migration.

UPDATE public.alpha_skill_registry
SET metadata = metadata - 'discovery'
WHERE metadata->'discovery'->>'mapping_source' = '20260702_151500_skill_discovery_mapping';

DO $$
DECLARE
    remaining_count INTEGER;
BEGIN
    SELECT COUNT(*)
      INTO remaining_count
      FROM public.alpha_skill_registry
     WHERE metadata->'discovery'->>'mapping_source' = '20260702_151500_skill_discovery_mapping';

    IF remaining_count <> 0 THEN
        RAISE EXCEPTION 'ROLLBACK skill discovery mapping FAILED: % rows still mapped', remaining_count;
    END IF;

    RAISE NOTICE 'ROLLBACK skill discovery mapping OK';
END $$;
