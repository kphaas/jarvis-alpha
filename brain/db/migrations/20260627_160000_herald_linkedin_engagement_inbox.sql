-- Herald LinkedIn engagement inbox.
-- Stores public LinkedIn items that need a reviewed reply draft. The read API
-- connector is still pending LinkedIn r_member_social approval.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260627160000);

CREATE TABLE IF NOT EXISTS public.alpha_herald_social_engagement_items (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform           TEXT NOT NULL DEFAULT 'linkedin'
                       CHECK (platform = 'linkedin'),
    source             TEXT NOT NULL DEFAULT 'manual'
                       CHECK (source IN ('manual', 'linkedin_api')),
    account_label      TEXT NOT NULL DEFAULT 'AT0',
    provider_item_urn  TEXT,
    provider_post_urn  TEXT,
    item_url           TEXT,
    author_name        TEXT NOT NULL,
    item_text          TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'needs_reply'
                       CHECK (status IN (
                           'needs_reply', 'draft_created',
                           'ignored', 'replied', 'archived'
                       )),
    reply_variant_id   UUID
                       REFERENCES public.alpha_herald_social_draft_variants(id),
    discovered_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by         TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alpha_herald_social_engagement_items_account_label_check
        CHECK (char_length(btrim(account_label)) BETWEEN 1 AND 80),
    CONSTRAINT alpha_herald_social_engagement_items_author_name_check
        CHECK (char_length(btrim(author_name)) BETWEEN 1 AND 160),
    CONSTRAINT alpha_herald_social_engagement_items_item_text_check
        CHECK (char_length(btrim(item_text)) BETWEEN 3 AND 1200),
    CONSTRAINT alpha_herald_social_engagement_items_item_url_check
        CHECK (
            item_url IS NULL
            OR char_length(btrim(item_url)) BETWEEN 8 AND 500
        ),
    CONSTRAINT alpha_herald_social_engagement_items_created_by_check
        CHECK (char_length(btrim(created_by)) BETWEEN 1 AND 160)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_herald_social_engagement_provider_item_urn
    ON public.alpha_herald_social_engagement_items(provider_item_urn)
    WHERE provider_item_urn IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_herald_social_engagement_status_discovered
    ON public.alpha_herald_social_engagement_items(status, discovered_at DESC);

ALTER TABLE public.alpha_herald_social_engagement_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_herald_social_engagement_items FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS herald_social_engagement_items_select
    ON public.alpha_herald_social_engagement_items;
CREATE POLICY herald_social_engagement_items_select
    ON public.alpha_herald_social_engagement_items
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS herald_social_engagement_items_write
    ON public.alpha_herald_social_engagement_items;
CREATE POLICY herald_social_engagement_items_write
    ON public.alpha_herald_social_engagement_items
    FOR INSERT
    WITH CHECK (true);

DROP POLICY IF EXISTS herald_social_engagement_items_update
    ON public.alpha_herald_social_engagement_items;
CREATE POLICY herald_social_engagement_items_update
    ON public.alpha_herald_social_engagement_items
    FOR UPDATE
    USING (true)
    WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE
    ON public.alpha_herald_social_engagement_items TO jarvis_alpha_writer;
GRANT SELECT
    ON public.alpha_herald_social_engagement_items TO jarvis_alpha_app;

COMMENT ON TABLE public.alpha_herald_social_engagement_items IS
    'Herald LinkedIn engagement inbox. Public social items only; no tokens, DMs, likes, or autonomous replies.';
COMMENT ON COLUMN public.alpha_herald_social_engagement_items.source IS
    'manual today; linkedin_api only after r_member_social read access is approved.';
COMMENT ON COLUMN public.alpha_herald_social_engagement_items.reply_variant_id IS
    'Approved publish still happens through alpha_herald_social_draft_variants after human review.';

COMMIT;
