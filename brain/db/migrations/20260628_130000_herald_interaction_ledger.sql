-- Herald unified interaction ledger.
-- One append-only metadata spine across Herald email and social. No mail body,
-- draft text, social item text, Graph tokens, or LinkedIn tokens are stored.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260628130000);

CREATE TABLE IF NOT EXISTS public.alpha_herald_interaction_ledger (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel            TEXT NOT NULL
                       CHECK (channel IN ('email', 'social', 'linkedin', 'x')),
    interaction_kind   TEXT NOT NULL
                       CHECK (interaction_kind IN (
                           'message', 'engagement', 'draft',
                           'approval', 'outbound', 'metric'
                       )),
    direction          TEXT NOT NULL
                       CHECK (direction IN ('inbound', 'outbound', 'internal')),
    lifecycle_event    TEXT NOT NULL,
    status             TEXT NOT NULL,
    account_label      TEXT NOT NULL DEFAULT 'AT0',
    primary_ref_type   TEXT NOT NULL,
    primary_ref_id     TEXT NOT NULL,
    secondary_ref_type TEXT,
    secondary_ref_id   TEXT,
    actor_sub          TEXT NOT NULL,
    actor_type         TEXT NOT NULL,
    related_refs       JSONB NOT NULL DEFAULT '{}'::jsonb,
    event_metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT alpha_herald_interaction_ledger_lifecycle_event_check
        CHECK (char_length(btrim(lifecycle_event)) BETWEEN 1 AND 120),
    CONSTRAINT alpha_herald_interaction_ledger_status_check
        CHECK (char_length(btrim(status)) BETWEEN 1 AND 80),
    CONSTRAINT alpha_herald_interaction_ledger_account_label_check
        CHECK (char_length(btrim(account_label)) BETWEEN 1 AND 80),
    CONSTRAINT alpha_herald_interaction_ledger_primary_ref_type_check
        CHECK (char_length(btrim(primary_ref_type)) BETWEEN 1 AND 80),
    CONSTRAINT alpha_herald_interaction_ledger_primary_ref_id_check
        CHECK (char_length(btrim(primary_ref_id)) BETWEEN 1 AND 240),
    CONSTRAINT alpha_herald_interaction_ledger_secondary_ref_type_check
        CHECK (
            secondary_ref_type IS NULL
            OR char_length(btrim(secondary_ref_type)) BETWEEN 1 AND 80
        ),
    CONSTRAINT alpha_herald_interaction_ledger_secondary_ref_id_check
        CHECK (
            secondary_ref_id IS NULL
            OR char_length(btrim(secondary_ref_id)) BETWEEN 1 AND 240
        ),
    CONSTRAINT alpha_herald_interaction_ledger_actor_sub_check
        CHECK (char_length(btrim(actor_sub)) BETWEEN 1 AND 160),
    CONSTRAINT alpha_herald_interaction_ledger_actor_type_check
        CHECK (char_length(btrim(actor_type)) BETWEEN 1 AND 80),
    CONSTRAINT alpha_herald_interaction_ledger_related_refs_object_check
        CHECK (jsonb_typeof(related_refs) = 'object'),
    CONSTRAINT alpha_herald_interaction_ledger_event_metadata_object_check
        CHECK (jsonb_typeof(event_metadata) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_herald_interaction_channel_status_created
    ON public.alpha_herald_interaction_ledger(channel, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_herald_interaction_primary_ref
    ON public.alpha_herald_interaction_ledger(primary_ref_type, primary_ref_id);

CREATE INDEX IF NOT EXISTS idx_herald_interaction_kind_created
    ON public.alpha_herald_interaction_ledger(interaction_kind, created_at DESC);

CREATE OR REPLACE FUNCTION public.alpha_herald_interaction_ledger_immutable()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $$
BEGIN
    RAISE EXCEPTION 'alpha_herald_interaction_ledger is append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_alpha_herald_interaction_ledger_immutable
    ON public.alpha_herald_interaction_ledger;
CREATE TRIGGER trg_alpha_herald_interaction_ledger_immutable
    BEFORE UPDATE OR DELETE ON public.alpha_herald_interaction_ledger
    FOR EACH ROW EXECUTE FUNCTION public.alpha_herald_interaction_ledger_immutable();

ALTER TABLE public.alpha_herald_interaction_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_herald_interaction_ledger FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS herald_interaction_ledger_select
    ON public.alpha_herald_interaction_ledger;
CREATE POLICY herald_interaction_ledger_select
    ON public.alpha_herald_interaction_ledger
    FOR SELECT
    USING (true);

DROP POLICY IF EXISTS herald_interaction_ledger_write
    ON public.alpha_herald_interaction_ledger;
CREATE POLICY herald_interaction_ledger_write
    ON public.alpha_herald_interaction_ledger
    FOR INSERT
    WITH CHECK (true);

GRANT SELECT, INSERT ON public.alpha_herald_interaction_ledger TO jarvis_alpha_writer;
GRANT SELECT ON public.alpha_herald_interaction_ledger TO jarvis_alpha_app;

COMMENT ON TABLE public.alpha_herald_interaction_ledger IS
    'Unified append-only Herald email/social interaction metadata ledger. No message bodies, draft text, item text, or platform tokens.';

COMMIT;
