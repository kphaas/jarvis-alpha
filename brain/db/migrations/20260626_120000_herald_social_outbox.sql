-- Herald social draft-only outbox.
-- Stores local social draft requests, per-platform variants, profile snapshots,
-- and append-only review events. No social platform publish connector exists here.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260626120000);

CREATE TABLE IF NOT EXISTS public.alpha_herald_social_platform_profiles (
    platform          TEXT PRIMARY KEY
                      CHECK (platform IN ('x', 'linkedin')),
    display_name      TEXT NOT NULL,
    account_label     TEXT NOT NULL DEFAULT 'AT0',
    audience_notes    TEXT NOT NULL,
    voice_rules       TEXT[] NOT NULL,
    safety_rules      TEXT[] NOT NULL,
    max_chars         INTEGER NOT NULL CHECK (max_chars BETWEEN 80 AND 4000),
    profile_version   INTEGER NOT NULL DEFAULT 1 CHECK (profile_version >= 1),
    active            BOOLEAN NOT NULL DEFAULT true,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alpha_herald_social_platform_profiles_voice_rules_check
        CHECK (cardinality(voice_rules) >= 1),
    CONSTRAINT alpha_herald_social_platform_profiles_safety_rules_check
        CHECK (cardinality(safety_rules) >= 1)
);

CREATE TABLE IF NOT EXISTS public.alpha_herald_social_draft_requests (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic          TEXT NOT NULL,
    source_url     TEXT,
    campaign       TEXT,
    account_label  TEXT NOT NULL DEFAULT 'AT0',
    status         TEXT NOT NULL DEFAULT 'drafted'
                   CHECK (status IN ('drafted', 'reviewed', 'archived')),
    requested_by   TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alpha_herald_social_draft_requests_topic_check
        CHECK (char_length(btrim(topic)) BETWEEN 3 AND 500),
    CONSTRAINT alpha_herald_social_draft_requests_source_url_check
        CHECK (source_url IS NULL OR char_length(btrim(source_url)) BETWEEN 8 AND 500),
    CONSTRAINT alpha_herald_social_draft_requests_requested_by_check
        CHECK (char_length(btrim(requested_by)) BETWEEN 1 AND 160)
);

CREATE TABLE IF NOT EXISTS public.alpha_herald_social_draft_variants (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id            UUID NOT NULL
                          REFERENCES public.alpha_herald_social_draft_requests(id)
                          ON DELETE CASCADE,
    platform              TEXT NOT NULL CHECK (platform IN ('x', 'linkedin')),
    account_label         TEXT NOT NULL DEFAULT 'AT0',
    draft_text            TEXT NOT NULL,
    content_hash          TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'needs_review'
                          CHECK (status IN (
                              'needs_review', 'approved', 'rejected', 'archived'
                          )),
    variant_version       INTEGER NOT NULL DEFAULT 1 CHECK (variant_version >= 1),
    profile_version       INTEGER NOT NULL CHECK (profile_version >= 1),
    audience_notes        TEXT NOT NULL,
    voice_rules           TEXT[] NOT NULL,
    safety_rules          TEXT[] NOT NULL,
    voice_score           NUMERIC(4, 2) NOT NULL DEFAULT 0.85
                          CHECK (voice_score >= 0 AND voice_score <= 1),
    safety_flags          TEXT[] NOT NULL DEFAULT ARRAY[]::text[],
    repeat_of_variant_id  UUID REFERENCES public.alpha_herald_social_draft_variants(id),
    reviewer_notes        TEXT,
    reviewed_by           TEXT,
    reviewed_at           TIMESTAMPTZ,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alpha_herald_social_draft_variants_content_hash_check
        CHECK (content_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT alpha_herald_social_draft_variants_draft_text_check
        CHECK (char_length(btrim(draft_text)) BETWEEN 3 AND 4000)
);

CREATE TABLE IF NOT EXISTS public.alpha_herald_social_draft_events (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id     UUID NOT NULL
                   REFERENCES public.alpha_herald_social_draft_requests(id)
                   ON DELETE CASCADE,
    variant_id     UUID
                   REFERENCES public.alpha_herald_social_draft_variants(id)
                   ON DELETE CASCADE,
    event_type     TEXT NOT NULL
                   CHECK (event_type IN (
                       'request_created', 'variant_created',
                       'variant_approved', 'variant_rejected', 'variant_archived'
                   )),
    actor_sub      TEXT NOT NULL,
    actor_type     TEXT NOT NULL,
    event_payload  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alpha_herald_social_draft_events_actor_sub_check
        CHECK (char_length(btrim(actor_sub)) BETWEEN 1 AND 160),
    CONSTRAINT alpha_herald_social_draft_events_actor_type_check
        CHECK (char_length(btrim(actor_type)) BETWEEN 1 AND 80),
    CONSTRAINT alpha_herald_social_draft_events_payload_object_check
        CHECK (jsonb_typeof(event_payload) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_herald_social_draft_requests_created
    ON public.alpha_herald_social_draft_requests(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_herald_social_draft_variants_status_created
    ON public.alpha_herald_social_draft_variants(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_herald_social_draft_variants_platform_hash
    ON public.alpha_herald_social_draft_variants(platform, content_hash);

CREATE INDEX IF NOT EXISTS idx_herald_social_draft_events_request
    ON public.alpha_herald_social_draft_events(request_id, created_at DESC);

CREATE OR REPLACE FUNCTION public.alpha_herald_social_draft_events_immutable()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $$
BEGIN
    RAISE EXCEPTION 'alpha_herald_social_draft_events is append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_alpha_herald_social_draft_events_immutable
    ON public.alpha_herald_social_draft_events;
CREATE TRIGGER trg_alpha_herald_social_draft_events_immutable
    BEFORE UPDATE OR DELETE ON public.alpha_herald_social_draft_events
    FOR EACH ROW EXECUTE FUNCTION public.alpha_herald_social_draft_events_immutable();

ALTER TABLE public.alpha_herald_social_platform_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_herald_social_platform_profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_herald_social_draft_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_herald_social_draft_requests FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_herald_social_draft_variants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_herald_social_draft_variants FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_herald_social_draft_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_herald_social_draft_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS herald_social_platform_profiles_select
    ON public.alpha_herald_social_platform_profiles;
CREATE POLICY herald_social_platform_profiles_select
    ON public.alpha_herald_social_platform_profiles
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS herald_social_platform_profiles_write
    ON public.alpha_herald_social_platform_profiles;
CREATE POLICY herald_social_platform_profiles_write
    ON public.alpha_herald_social_platform_profiles
    FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS herald_social_platform_profiles_update
    ON public.alpha_herald_social_platform_profiles;
CREATE POLICY herald_social_platform_profiles_update
    ON public.alpha_herald_social_platform_profiles
    FOR UPDATE
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS herald_social_draft_requests_select
    ON public.alpha_herald_social_draft_requests;
CREATE POLICY herald_social_draft_requests_select
    ON public.alpha_herald_social_draft_requests
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS herald_social_draft_requests_write
    ON public.alpha_herald_social_draft_requests;
CREATE POLICY herald_social_draft_requests_write
    ON public.alpha_herald_social_draft_requests
    FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS herald_social_draft_requests_update
    ON public.alpha_herald_social_draft_requests;
CREATE POLICY herald_social_draft_requests_update
    ON public.alpha_herald_social_draft_requests
    FOR UPDATE
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS herald_social_draft_variants_select
    ON public.alpha_herald_social_draft_variants;
CREATE POLICY herald_social_draft_variants_select
    ON public.alpha_herald_social_draft_variants
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS herald_social_draft_variants_write
    ON public.alpha_herald_social_draft_variants;
CREATE POLICY herald_social_draft_variants_write
    ON public.alpha_herald_social_draft_variants
    FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS herald_social_draft_variants_update
    ON public.alpha_herald_social_draft_variants;
CREATE POLICY herald_social_draft_variants_update
    ON public.alpha_herald_social_draft_variants
    FOR UPDATE
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS herald_social_draft_events_select
    ON public.alpha_herald_social_draft_events;
CREATE POLICY herald_social_draft_events_select
    ON public.alpha_herald_social_draft_events
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS herald_social_draft_events_write
    ON public.alpha_herald_social_draft_events;
CREATE POLICY herald_social_draft_events_write
    ON public.alpha_herald_social_draft_events
    FOR INSERT
    WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE
    ON public.alpha_herald_social_platform_profiles TO jarvis_alpha_writer;
GRANT SELECT, INSERT, UPDATE
    ON public.alpha_herald_social_draft_requests TO jarvis_alpha_writer;
GRANT SELECT, INSERT, UPDATE
    ON public.alpha_herald_social_draft_variants TO jarvis_alpha_writer;
GRANT SELECT, INSERT
    ON public.alpha_herald_social_draft_events TO jarvis_alpha_writer;

GRANT SELECT ON public.alpha_herald_social_platform_profiles TO jarvis_alpha_app;
GRANT SELECT ON public.alpha_herald_social_draft_requests TO jarvis_alpha_app;
GRANT SELECT ON public.alpha_herald_social_draft_variants TO jarvis_alpha_app;
GRANT SELECT ON public.alpha_herald_social_draft_events TO jarvis_alpha_app;

INSERT INTO public.alpha_herald_social_platform_profiles (
    platform, display_name, account_label, audience_notes,
    voice_rules, safety_rules, max_chars, profile_version, active
) VALUES
(
    'x',
    'X',
    'AT0',
    'Builders, privacy/self-hosting people, AI tinkerers, and fast-scrolling technical readers.',
    ARRAY[
        'Calm, concrete, low-hype.',
        'One clear point per post.',
        'Lead with the benefit, then the mechanism.',
        'Use AT0, never AT-0.'
    ],
    ARRAY[
        'No autonomous engagement claims.',
        'Say planned when a capability is planned.',
        'No revolutionary/game-changing/next-gen language.',
        'No publish without human approval.'
    ],
    280,
    1,
    true
),
(
    'linkedin',
    'LinkedIn',
    'AT0',
    'Technical professionals, AI builders, privacy-aware operators, and early-access evaluators.',
    ARRAY[
        'Calm, concrete, human, confident.',
        'Use short paragraphs and specific evidence.',
        'Connect the story to private infrastructure and memory.',
        'Use AT0, never AT-0.'
    ],
    ARRAY[
        'No overpromising.',
        'No invented customer or traction claims.',
        'Say planned when a capability is planned.',
        'No publish without human approval.'
    ],
    3000,
    1,
    true
)
ON CONFLICT (platform) DO UPDATE
SET display_name = EXCLUDED.display_name,
    account_label = EXCLUDED.account_label,
    audience_notes = EXCLUDED.audience_notes,
    voice_rules = EXCLUDED.voice_rules,
    safety_rules = EXCLUDED.safety_rules,
    max_chars = EXCLUDED.max_chars,
    profile_version = EXCLUDED.profile_version,
    active = EXCLUDED.active,
    updated_at = now();

COMMENT ON TABLE public.alpha_herald_social_platform_profiles IS
    'Herald social platform voice memory. Read by the draft-only outbox; no tokens or publish credentials.';

COMMENT ON TABLE public.alpha_herald_social_draft_variants IS
    'Local Herald social draft variants awaiting human review. Does not publish to social platforms.';

COMMENT ON TABLE public.alpha_herald_social_draft_events IS
    'Append-only Herald social review audit. Stores metadata only; no platform tokens.';

COMMIT;
