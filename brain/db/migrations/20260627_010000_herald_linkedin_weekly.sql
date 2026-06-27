-- Herald LinkedIn weekly cadence and manual publish receipts.
-- Extends the local social approval outbox; still no LinkedIn platform publish connector.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260627010000);

ALTER TABLE public.alpha_herald_social_draft_requests
    ADD COLUMN IF NOT EXISTS draft_kind TEXT NOT NULL DEFAULT 'post';

ALTER TABLE public.alpha_herald_social_draft_requests
    ADD COLUMN IF NOT EXISTS engagement_author TEXT;

ALTER TABLE public.alpha_herald_social_draft_requests
    DROP CONSTRAINT IF EXISTS alpha_herald_social_draft_requests_draft_kind_check;
ALTER TABLE public.alpha_herald_social_draft_requests
    ADD CONSTRAINT alpha_herald_social_draft_requests_draft_kind_check
    CHECK (draft_kind IN ('post', 'reply'));

ALTER TABLE public.alpha_herald_social_draft_requests
    DROP CONSTRAINT IF EXISTS alpha_herald_social_draft_requests_engagement_author_check;
ALTER TABLE public.alpha_herald_social_draft_requests
    ADD CONSTRAINT alpha_herald_social_draft_requests_engagement_author_check
    CHECK (
        engagement_author IS NULL
        OR char_length(btrim(engagement_author)) BETWEEN 1 AND 120
    );

ALTER TABLE public.alpha_herald_social_draft_variants
    ADD COLUMN IF NOT EXISTS scheduled_for DATE;

ALTER TABLE public.alpha_herald_social_draft_variants
    ADD COLUMN IF NOT EXISTS publish_status TEXT NOT NULL DEFAULT 'not_scheduled';

ALTER TABLE public.alpha_herald_social_draft_variants
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;

ALTER TABLE public.alpha_herald_social_draft_variants
    ADD COLUMN IF NOT EXISTS published_url TEXT;

ALTER TABLE public.alpha_herald_social_draft_variants
    DROP CONSTRAINT IF EXISTS alpha_herald_social_draft_variants_publish_status_check;
ALTER TABLE public.alpha_herald_social_draft_variants
    ADD CONSTRAINT alpha_herald_social_draft_variants_publish_status_check
    CHECK (publish_status IN ('not_scheduled', 'scheduled', 'manual_published'));

ALTER TABLE public.alpha_herald_social_draft_variants
    DROP CONSTRAINT IF EXISTS alpha_herald_social_draft_variants_published_url_check;
ALTER TABLE public.alpha_herald_social_draft_variants
    ADD CONSTRAINT alpha_herald_social_draft_variants_published_url_check
    CHECK (
        published_url IS NULL
        OR char_length(btrim(published_url)) BETWEEN 8 AND 500
    );

ALTER TABLE public.alpha_herald_social_draft_events
    DROP CONSTRAINT IF EXISTS alpha_herald_social_draft_events_event_type_check;
ALTER TABLE public.alpha_herald_social_draft_events
    ADD CONSTRAINT alpha_herald_social_draft_events_event_type_check
    CHECK (event_type IN (
        'request_created', 'variant_created',
        'variant_approved', 'variant_rejected', 'variant_archived',
        'variant_scheduled', 'variant_manual_published'
    ));

CREATE INDEX IF NOT EXISTS idx_herald_social_draft_variants_linkedin_schedule
    ON public.alpha_herald_social_draft_variants(platform, publish_status, scheduled_for)
    WHERE platform = 'linkedin';

COMMENT ON COLUMN public.alpha_herald_social_draft_requests.draft_kind IS
    'post for original social content; reply for reviewed engagement response drafts.';
COMMENT ON COLUMN public.alpha_herald_social_draft_requests.engagement_author IS
    'Optional public author/display name for reply drafts; do not store private identifiers here.';
COMMENT ON COLUMN public.alpha_herald_social_draft_variants.scheduled_for IS
    'Operator-selected intended publish date. This does not publish to LinkedIn.';
COMMENT ON COLUMN public.alpha_herald_social_draft_variants.publish_status IS
    'Manual lifecycle marker for approved LinkedIn posts/replies. No platform connector is invoked.';
COMMENT ON COLUMN public.alpha_herald_social_draft_variants.published_url IS
    'Operator-provided URL after a manual publish on the social platform.';

COMMIT;
