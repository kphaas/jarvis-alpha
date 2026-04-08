-- Migration 20260408_140000: fix record_buddy_event type mismatches
-- Schema reality: id UUID (not BIGINT), priority INTEGER (not TEXT), user_id nullable
-- Drop old function signature, recreate with correct types

DROP FUNCTION IF EXISTS public.record_buddy_event(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB);

CREATE OR REPLACE FUNCTION public.record_buddy_event(
  p_user_id TEXT,
  p_event_type TEXT,
  p_title TEXT,
  p_body TEXT,
  p_priority INTEGER,
  p_source TEXT,
  p_payload JSONB
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  v_id UUID;
BEGIN
  SET LOCAL lock_timeout = '2s';
  SET LOCAL statement_timeout = '10s';
  
  -- event_type must match CHECK constraint: alert | reminder | suggestion | system
  -- priority integer scale: 1=low, 2=normal, 3=high
  -- user_id is nullable per schema; 'system' sentinel convention per PATTERNS.md §15
  
  INSERT INTO public.alpha_buddy_events
    (user_id, event_type, title, body, priority, source, payload)
  VALUES
    (p_user_id, p_event_type, p_title, p_body, p_priority, p_source, p_payload)
  RETURNING id INTO v_id;
  
  RETURN v_id;
EXCEPTION
  WHEN OTHERS THEN
    -- Audit-critical: re-raise all errors
    RAISE;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.record_buddy_event(TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.record_buddy_event(TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, JSONB) TO jarvis_alpha_writer;
GRANT EXECUTE ON FUNCTION public.record_buddy_event(TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, JSONB) TO jarvisbrain;

COMMENT ON FUNCTION public.record_buddy_event IS 
  'Step 6.5 Stage 3 (fixed 20260408_140000): SECURITY DEFINER wrapper for alpha_buddy_events writes. Returns UUID. Priority scale 1=low, 2=normal, 3=high. event_type must be alert|reminder|suggestion|system. Re-raises all errors (audit-critical).';
