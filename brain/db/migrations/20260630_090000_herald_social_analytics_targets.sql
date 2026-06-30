-- Herald social analytics feedback loop and thought-leader target graph.
-- Metrics stay local and metadata-only. Platform tokens, bodies, and private DMs
-- are not stored here.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260630090000);

CREATE TABLE IF NOT EXISTS public.alpha_herald_social_metric_snapshots (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    variant_id         UUID NOT NULL
                       REFERENCES public.alpha_herald_social_draft_variants(id)
                       ON DELETE CASCADE,
    engagement_item_id UUID
                       REFERENCES public.alpha_herald_social_engagement_items(id)
                       ON DELETE SET NULL,
    platform           TEXT NOT NULL DEFAULT 'linkedin'
                       CHECK (platform = 'linkedin'),
    metric_source      TEXT NOT NULL DEFAULT 'manual'
                       CHECK (metric_source IN ('manual', 'linkedin_api')),
    impressions        INTEGER NOT NULL DEFAULT 0 CHECK (impressions >= 0),
    reactions          INTEGER NOT NULL DEFAULT 0 CHECK (reactions >= 0),
    comments           INTEGER NOT NULL DEFAULT 0 CHECK (comments >= 0),
    reposts            INTEGER NOT NULL DEFAULT 0 CHECK (reposts >= 0),
    profile_clicks     INTEGER NOT NULL DEFAULT 0 CHECK (profile_clicks >= 0),
    captured_on        DATE NOT NULL DEFAULT current_date,
    recorded_by        TEXT NOT NULL,
    notes              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alpha_herald_social_metric_recorded_by_check
        CHECK (char_length(btrim(recorded_by)) BETWEEN 1 AND 160),
    CONSTRAINT alpha_herald_social_metric_notes_check
        CHECK (notes IS NULL OR char_length(btrim(notes)) <= 500)
);

CREATE INDEX IF NOT EXISTS idx_herald_social_metric_variant_created
    ON public.alpha_herald_social_metric_snapshots(variant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_herald_social_metric_captured
    ON public.alpha_herald_social_metric_snapshots(captured_on DESC);

CREATE TABLE IF NOT EXISTS public.alpha_herald_thought_leader_targets (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform            TEXT NOT NULL DEFAULT 'linkedin'
                        CHECK (platform = 'linkedin'),
    person_name         TEXT NOT NULL,
    company_name        TEXT,
    role_title          TEXT,
    profile_url         TEXT,
    topics              TEXT[] NOT NULL DEFAULT ARRAY[]::text[],
    priority            INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    relationship_notes  TEXT,
    last_interaction_at TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'paused', 'archived')),
    created_by          TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alpha_herald_thought_leader_person_check
        CHECK (char_length(btrim(person_name)) BETWEEN 1 AND 160),
    CONSTRAINT alpha_herald_thought_leader_company_check
        CHECK (company_name IS NULL OR char_length(btrim(company_name)) <= 160),
    CONSTRAINT alpha_herald_thought_leader_role_check
        CHECK (role_title IS NULL OR char_length(btrim(role_title)) <= 160),
    CONSTRAINT alpha_herald_thought_leader_url_check
        CHECK (profile_url IS NULL OR char_length(btrim(profile_url)) BETWEEN 8 AND 500),
    CONSTRAINT alpha_herald_thought_leader_notes_check
        CHECK (
            relationship_notes IS NULL
            OR char_length(btrim(relationship_notes)) <= 1000
        ),
    CONSTRAINT alpha_herald_thought_leader_created_by_check
        CHECK (char_length(btrim(created_by)) BETWEEN 1 AND 160)
);

CREATE INDEX IF NOT EXISTS idx_herald_thought_leader_status_priority
    ON public.alpha_herald_thought_leader_targets(status, priority, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_herald_thought_leader_topics
    ON public.alpha_herald_thought_leader_targets USING gin(topics);

ALTER TABLE public.alpha_herald_social_metric_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_herald_social_metric_snapshots FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_herald_thought_leader_targets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_herald_thought_leader_targets FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS herald_social_metric_snapshots_select
    ON public.alpha_herald_social_metric_snapshots;
CREATE POLICY herald_social_metric_snapshots_select
    ON public.alpha_herald_social_metric_snapshots
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS herald_social_metric_snapshots_write
    ON public.alpha_herald_social_metric_snapshots;
CREATE POLICY herald_social_metric_snapshots_write
    ON public.alpha_herald_social_metric_snapshots
    FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS herald_thought_leader_targets_select
    ON public.alpha_herald_thought_leader_targets;
CREATE POLICY herald_thought_leader_targets_select
    ON public.alpha_herald_thought_leader_targets
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS herald_thought_leader_targets_write
    ON public.alpha_herald_thought_leader_targets;
CREATE POLICY herald_thought_leader_targets_write
    ON public.alpha_herald_thought_leader_targets
    FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS herald_thought_leader_targets_update
    ON public.alpha_herald_thought_leader_targets;
CREATE POLICY herald_thought_leader_targets_update
    ON public.alpha_herald_thought_leader_targets
    FOR UPDATE
    USING (true)
    WITH CHECK (true);

GRANT SELECT, INSERT
    ON public.alpha_herald_social_metric_snapshots TO jarvis_alpha_writer;
GRANT SELECT, INSERT, UPDATE
    ON public.alpha_herald_thought_leader_targets TO jarvis_alpha_writer;

GRANT SELECT ON public.alpha_herald_social_metric_snapshots TO jarvis_alpha_app;
GRANT SELECT ON public.alpha_herald_thought_leader_targets TO jarvis_alpha_app;

COMMENT ON TABLE public.alpha_herald_social_metric_snapshots IS
    'Herald social post/comment metric snapshots. Local metadata only; no platform token or private message storage.';
COMMENT ON TABLE public.alpha_herald_thought_leader_targets IS
    'Herald LinkedIn thought-leader target graph for reviewed brand engagement planning.';

COMMIT;
