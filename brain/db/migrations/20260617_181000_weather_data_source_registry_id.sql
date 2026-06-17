-- Migration: 20260617_181000_weather_data_source_registry_id
-- Purpose:   Link weather.current to the vendored jarvis-data-sources entry.

UPDATE public.alpha_skill_registry
   SET metadata = jsonb_set(
           metadata,
           '{manifest,egress,data_source_id}',
           to_jsonb('open-meteo'::text),
           true
       ),
       updated_at = NOW()
 WHERE skill_name = 'weather.current'
   AND metadata->'manifest'->'egress'->>'provider' = 'open_meteo';

DO $$
DECLARE
    v_skill_count integer;
BEGIN
    SELECT COUNT(*)
      INTO v_skill_count
      FROM public.alpha_skill_registry
     WHERE skill_name = 'weather.current'
       AND metadata->'manifest'->'egress'->>'provider' = 'open_meteo'
       AND metadata->'manifest'->'egress'->>'data_source_id' = 'open-meteo';

    IF v_skill_count <> 1 THEN
        RAISE EXCEPTION 'POST-FLIGHT weather.current data source link FAILED: count=%', v_skill_count;
    END IF;

    RAISE NOTICE 'POST-FLIGHT weather.current data source link OK';
END $$;
