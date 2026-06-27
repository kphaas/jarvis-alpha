-- Herald LinkedIn approved publish path.
-- Adds direct publish state only after a Herald social draft is approved.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260627120000);

ALTER TABLE public.alpha_herald_social_draft_variants
    ADD COLUMN IF NOT EXISTS publish_attempt_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE public.alpha_herald_social_draft_variants
    ADD COLUMN IF NOT EXISTS last_publish_attempt_at TIMESTAMPTZ;

ALTER TABLE public.alpha_herald_social_draft_variants
    ADD COLUMN IF NOT EXISTS publish_error_type TEXT;

ALTER TABLE public.alpha_herald_social_draft_variants
    ADD COLUMN IF NOT EXISTS publish_error_message TEXT;

ALTER TABLE public.alpha_herald_social_draft_variants
    ADD COLUMN IF NOT EXISTS provider_post_urn TEXT;

ALTER TABLE public.alpha_herald_social_draft_variants
    DROP CONSTRAINT IF EXISTS alpha_herald_social_draft_variants_publish_attempt_count_check;
ALTER TABLE public.alpha_herald_social_draft_variants
    ADD CONSTRAINT alpha_herald_social_draft_variants_publish_attempt_count_check
    CHECK (publish_attempt_count >= 0);

ALTER TABLE public.alpha_herald_social_draft_variants
    DROP CONSTRAINT IF EXISTS alpha_herald_social_draft_variants_publish_status_check;
ALTER TABLE public.alpha_herald_social_draft_variants
    ADD CONSTRAINT alpha_herald_social_draft_variants_publish_status_check
    CHECK (publish_status IN (
        'not_scheduled', 'scheduled', 'manual_published',
        'sending', 'linkedin_published', 'publish_failed'
    ));

ALTER TABLE public.alpha_herald_social_draft_variants
    DROP CONSTRAINT IF EXISTS alpha_herald_social_draft_variants_provider_post_urn_check;
ALTER TABLE public.alpha_herald_social_draft_variants
    ADD CONSTRAINT alpha_herald_social_draft_variants_provider_post_urn_check
    CHECK (
        provider_post_urn IS NULL
        OR provider_post_urn ~ '^urn:li:[A-Za-z]+:[A-Za-z0-9_-]+$'
    );

ALTER TABLE public.alpha_herald_social_draft_events
    DROP CONSTRAINT IF EXISTS alpha_herald_social_draft_events_event_type_check;
ALTER TABLE public.alpha_herald_social_draft_events
    ADD CONSTRAINT alpha_herald_social_draft_events_event_type_check
    CHECK (event_type IN (
        'request_created', 'variant_created',
        'variant_approved', 'variant_rejected', 'variant_archived',
        'variant_scheduled', 'variant_manual_published',
        'variant_linkedin_publish_started',
        'variant_linkedin_published',
        'variant_linkedin_publish_failed'
    ));

COMMENT ON COLUMN public.alpha_herald_social_draft_variants.publish_attempt_count IS
    'Count of approved LinkedIn publish attempts for this variant.';
COMMENT ON COLUMN public.alpha_herald_social_draft_variants.provider_post_urn IS
    'LinkedIn post URN returned by the Gateway connector; never an access token.';

COMMIT;
