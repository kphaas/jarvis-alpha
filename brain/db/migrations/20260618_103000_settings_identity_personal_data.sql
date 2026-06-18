-- Migration: 20260618_103000_settings_identity_personal_data
-- Purpose:   Add Alpha Settings identity/personal-data tables without
--            mixing personal information into auth-only fields or secrets.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(2026061802);

CREATE TABLE IF NOT EXISTS public.alpha_profile_personal_data (
    profile_id             TEXT PRIMARY KEY
                           REFERENCES public.alpha_profiles(id)
                           ON DELETE CASCADE,
    legal_name             TEXT,
    preferred_name         TEXT,
    email                  TEXT,
    phone                  TEXT,
    birthday               DATE,
    notes                  TEXT,
    updated_by_profile_id  TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.alpha_profile_relationships (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_profile_id             TEXT NOT NULL
                                REFERENCES public.alpha_profiles(id)
                                ON DELETE CASCADE,
    to_profile_id               TEXT NOT NULL
                                REFERENCES public.alpha_profiles(id)
                                ON DELETE CASCADE,
    relationship_label          TEXT NOT NULL,
    inverse_relationship_label  TEXT,
    notes                       TEXT,
    updated_by_profile_id       TEXT,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alpha_profile_relationships_distinct_profiles
        CHECK (from_profile_id <> to_profile_id),
    CONSTRAINT alpha_profile_relationships_nonblank_label
        CHECK (btrim(relationship_label) <> ''),
    CONSTRAINT alpha_profile_relationships_unique_pair
        UNIQUE (from_profile_id, to_profile_id)
);

CREATE TABLE IF NOT EXISTS public.alpha_personal_data_settings (
    id                     INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    home_address           JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_by_profile_id  TEXT,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alpha_personal_data_home_address_object
        CHECK (jsonb_typeof(home_address) = 'object')
);

INSERT INTO public.alpha_personal_data_settings (id, home_address)
VALUES (1, '{}'::jsonb)
ON CONFLICT (id) DO NOTHING;

ALTER TABLE public.alpha_profile_personal_data ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS alpha_profile_personal_data_platform_admin
    ON public.alpha_profile_personal_data;
CREATE POLICY alpha_profile_personal_data_platform_admin
    ON public.alpha_profile_personal_data
    AS PERMISSIVE FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');
ALTER TABLE public.alpha_profile_personal_data FORCE ROW LEVEL SECURITY;

ALTER TABLE public.alpha_profile_relationships ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS alpha_profile_relationships_platform_admin
    ON public.alpha_profile_relationships;
CREATE POLICY alpha_profile_relationships_platform_admin
    ON public.alpha_profile_relationships
    AS PERMISSIVE FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');
ALTER TABLE public.alpha_profile_relationships FORCE ROW LEVEL SECURITY;

ALTER TABLE public.alpha_personal_data_settings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS alpha_personal_data_settings_platform_admin
    ON public.alpha_personal_data_settings;
CREATE POLICY alpha_personal_data_settings_platform_admin
    ON public.alpha_personal_data_settings
    AS PERMISSIVE FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');
ALTER TABLE public.alpha_personal_data_settings FORCE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_profile_personal_data
    TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_profile_relationships
    TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE ON public.alpha_personal_data_settings
    TO jarvis_alpha_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_profile_personal_data
    TO jarvis_alpha_writer;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_profile_relationships
    TO jarvis_alpha_writer;
GRANT SELECT, INSERT, UPDATE ON public.alpha_personal_data_settings
    TO jarvis_alpha_writer;

COMMENT ON TABLE public.alpha_profile_personal_data IS
    'Admin-only Alpha Settings personal information. API secrets and credentials must not be stored here.';
COMMENT ON TABLE public.alpha_profile_relationships IS
    'Admin-only Alpha Settings relationship graph between Alpha profiles.';
COMMENT ON TABLE public.alpha_personal_data_settings IS
    'Admin-only household personal data for local Alpha workflows. API secrets and credentials must not be stored here.';

DO $postcheck$
DECLARE
    v_bad TEXT[];
BEGIN
    WITH target(table_name) AS (
        VALUES
            ('alpha_profile_personal_data'),
            ('alpha_profile_relationships'),
            ('alpha_personal_data_settings')
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
        RAISE EXCEPTION 'POST-FLIGHT settings identity personal data RLS failed: %', v_bad;
    END IF;

    RAISE NOTICE 'POST-FLIGHT settings identity personal data RLS OK';
END
$postcheck$;

COMMIT;
