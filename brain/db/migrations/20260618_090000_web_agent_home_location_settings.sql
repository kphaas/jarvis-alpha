-- Migration: 20260618_090000_web_agent_home_location_settings
-- Purpose:   Store Web Agent personal settings in Alpha DB instead of
--            mixing personal information into API-secret files.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(2026061801);

CREATE TABLE IF NOT EXISTS public.alpha_web_agent_settings (
    id                    INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    home_location          JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_by_profile_id  TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alpha_web_agent_home_location_object
        CHECK (jsonb_typeof(home_location) = 'object'),
    CONSTRAINT alpha_web_agent_home_latitude_number
        CHECK (
            NOT (home_location ? 'latitude')
            OR jsonb_typeof(home_location -> 'latitude') = 'number'
        ),
    CONSTRAINT alpha_web_agent_home_longitude_number
        CHECK (
            NOT (home_location ? 'longitude')
            OR jsonb_typeof(home_location -> 'longitude') = 'number'
        )
);

INSERT INTO public.alpha_web_agent_settings (id, home_location)
VALUES (1, '{}'::jsonb)
ON CONFLICT (id) DO NOTHING;

ALTER TABLE public.alpha_web_agent_settings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS alpha_web_agent_settings_platform_admin
    ON public.alpha_web_agent_settings;
CREATE POLICY alpha_web_agent_settings_platform_admin
    ON public.alpha_web_agent_settings
    AS PERMISSIVE FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');
ALTER TABLE public.alpha_web_agent_settings FORCE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE ON public.alpha_web_agent_settings TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE ON public.alpha_web_agent_settings TO jarvis_alpha_writer;

DO $postcheck$
DECLARE
    v_bad TEXT[];
BEGIN
    WITH target(table_name) AS (
        VALUES ('alpha_web_agent_settings')
    )
    SELECT array_agg(t.table_name ORDER BY t.table_name)
      INTO v_bad
      FROM target t
      JOIN pg_class c ON c.relname = t.table_name
      JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
      LEFT JOIN (
        SELECT polrelid, count(*) AS policy_count
          FROM pg_policy
         GROUP BY polrelid
      ) p ON p.polrelid = c.oid
     WHERE NOT c.relrowsecurity
        OR NOT c.relforcerowsecurity
        OR COALESCE(p.policy_count, 0) = 0;

    IF v_bad IS NOT NULL THEN
        RAISE EXCEPTION 'POST-FLIGHT web agent settings RLS failed: %', v_bad;
    END IF;

    RAISE NOTICE 'POST-FLIGHT web agent settings RLS OK';
END
$postcheck$;

COMMIT;
