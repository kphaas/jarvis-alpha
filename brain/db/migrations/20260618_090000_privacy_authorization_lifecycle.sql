-- Purpose: P5-A Privacy Agent authorization vault + removal lifecycle.
-- Adds a local removal-request ledger and event stream. This is a control-plane
-- state machine only; it does not create outbound broker execution.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260618090000);

DO $preflight$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'alpha_privacy_authorizations'
    ) THEN
        RAISE EXCEPTION 'privacy lifecycle preflight failed; authorizations table missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'alpha_privacy_actions'
    ) THEN
        RAISE EXCEPTION 'privacy lifecycle preflight failed; actions table missing';
    END IF;
END
$preflight$;

CREATE TABLE IF NOT EXISTS public.alpha_privacy_removal_requests (
    id                              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id                      UUID NOT NULL
                                    REFERENCES public.alpha_privacy_subjects(id)
                                    ON DELETE RESTRICT,
    target_id                       TEXT NOT NULL
                                    REFERENCES public.alpha_privacy_targets_cache(id)
                                    ON DELETE RESTRICT,
    authorization_id                UUID NOT NULL
                                    REFERENCES public.alpha_privacy_authorizations(id)
                                    ON DELETE RESTRICT,
    action_id                       UUID
                                    REFERENCES public.alpha_privacy_actions(id)
                                    ON DELETE RESTRICT,
    lifecycle_status                TEXT NOT NULL DEFAULT 'queued'
                                    CHECK (lifecycle_status IN (
                                        'draft',
                                        'approved',
                                        'queued',
                                        'sent',
                                        'acknowledged',
                                        'monitoring',
                                        'completed',
                                        'failed',
                                        'escalated',
                                        'blocked'
                                    )),
    request_payload_ciphertext       BYTEA NOT NULL,
    request_payload_hash             TEXT NOT NULL,
    payload_key_version             TEXT NOT NULL,
    current_evidence_count          INTEGER NOT NULL DEFAULT 0
                                    CHECK (current_evidence_count >= 0),
    next_check_at                   TIMESTAMPTZ,
    last_event_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id              TEXT NOT NULL,
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT privacy_removal_request_payload_hash_check
        CHECK (request_payload_hash ~ '^sha256:[a-f0-9]{64}$'),
    CONSTRAINT privacy_removal_request_action_unique
        UNIQUE (action_id),
    CONSTRAINT privacy_removal_request_subject_authorization_check
        CHECK (subject_id IS NOT NULL AND authorization_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_privacy_removal_requests_subject
    ON public.alpha_privacy_removal_requests(subject_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_privacy_removal_requests_target
    ON public.alpha_privacy_removal_requests(target_id, lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_privacy_removal_requests_status
    ON public.alpha_privacy_removal_requests(lifecycle_status, next_check_at);
CREATE INDEX IF NOT EXISTS idx_privacy_removal_requests_authorization
    ON public.alpha_privacy_removal_requests(authorization_id);

ALTER TABLE public.alpha_privacy_removal_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_privacy_removal_requests FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_removal_requests_isolation
    ON public.alpha_privacy_removal_requests;
CREATE POLICY privacy_removal_requests_isolation
    ON public.alpha_privacy_removal_requests
    FOR ALL
    USING (
        subject_id IN (
            SELECT id
            FROM public.alpha_privacy_subjects
            WHERE user_id = current_setting('rls.user_id', true)
               OR guardian_user_id = current_setting('rls.user_id', true)
               OR current_setting('rls.role', true) = 'platform_admin'
        )
    )
    WITH CHECK (
        subject_id IN (
            SELECT id
            FROM public.alpha_privacy_subjects
            WHERE user_id = current_setting('rls.user_id', true)
               OR guardian_user_id = current_setting('rls.user_id', true)
               OR current_setting('rls.role', true) = 'platform_admin'
        )
    );

CREATE TABLE IF NOT EXISTS public.alpha_privacy_removal_request_events (
    id                             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id                     UUID NOT NULL
                                   REFERENCES public.alpha_privacy_removal_requests(id)
                                   ON DELETE RESTRICT,
    event_type                     TEXT NOT NULL
                                   CHECK (event_type IN (
                                       'created',
                                       'approved',
                                       'queued',
                                       'sent',
                                       'acknowledged',
                                       'monitoring',
                                       'completed',
                                       'failed',
                                       'escalated',
                                       'blocked',
                                       'proof_attached',
                                       'note'
                                   )),
    actor                          TEXT NOT NULL,
    event_payload_ciphertext        BYTEA,
    event_payload_hash              TEXT,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT privacy_removal_request_event_payload_hash_check
        CHECK (event_payload_hash IS NULL OR event_payload_hash ~ '^sha256:[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_privacy_removal_request_events_request
    ON public.alpha_privacy_removal_request_events(request_id, created_at);

ALTER TABLE public.alpha_privacy_removal_request_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_privacy_removal_request_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_removal_request_events_isolation
    ON public.alpha_privacy_removal_request_events;
CREATE POLICY privacy_removal_request_events_isolation
    ON public.alpha_privacy_removal_request_events
    FOR ALL
    USING (
        request_id IN (
            SELECT request.id
            FROM public.alpha_privacy_removal_requests AS request
            JOIN public.alpha_privacy_subjects AS subject
              ON subject.id = request.subject_id
            WHERE subject.user_id = current_setting('rls.user_id', true)
               OR subject.guardian_user_id = current_setting('rls.user_id', true)
               OR current_setting('rls.role', true) = 'platform_admin'
        )
    )
    WITH CHECK (
        request_id IN (
            SELECT request.id
            FROM public.alpha_privacy_removal_requests AS request
            JOIN public.alpha_privacy_subjects AS subject
              ON subject.id = request.subject_id
            WHERE subject.user_id = current_setting('rls.user_id', true)
               OR subject.guardian_user_id = current_setting('rls.user_id', true)
               OR current_setting('rls.role', true) = 'platform_admin'
        )
    );

ALTER TABLE public.alpha_privacy_evidence_items
    ADD COLUMN IF NOT EXISTS removal_request_id UUID
    REFERENCES public.alpha_privacy_removal_requests(id)
    ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_privacy_evidence_removal_request
    ON public.alpha_privacy_evidence_items(removal_request_id)
    WHERE removal_request_id IS NOT NULL;

DROP TRIGGER IF EXISTS trg_privacy_removal_requests_updated_at
    ON public.alpha_privacy_removal_requests;
CREATE TRIGGER trg_privacy_removal_requests_updated_at
    BEFORE UPDATE ON public.alpha_privacy_removal_requests
    FOR EACH ROW
    EXECUTE FUNCTION public.privacy_scrub_touch_updated_at();

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_privacy_removal_requests,
               public.alpha_privacy_removal_request_events
            TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_privacy_removal_requests,
               public.alpha_privacy_removal_request_events
            TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON TABLE public.alpha_privacy_removal_requests IS
    'Encrypted local lifecycle ledger for privacy removal requests. No outbound execution is represented by this table.';
COMMENT ON TABLE public.alpha_privacy_removal_request_events IS
    'Encrypted/hash-only event stream for local privacy removal request lifecycle transitions.';
COMMENT ON COLUMN public.alpha_privacy_evidence_items.removal_request_id IS
    'Optional link from evidence proof to the local removal-request lifecycle ledger.';

DO $postcheck$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relname IN (
            'alpha_privacy_removal_requests',
            'alpha_privacy_removal_request_events'
        )
        AND NOT (relrowsecurity AND relforcerowsecurity)
    ) THEN
        RAISE EXCEPTION 'privacy lifecycle FORCE RLS postcheck failed';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_proc
        WHERE pronamespace = 'public'::regnamespace
          AND proname IN (
              'privacy_decrypt_payload',
              'get_privacy_payload',
              'read_privacy_payload'
          )
    ) THEN
        RAISE EXCEPTION 'privacy lifecycle must not expose decrypt helpers';
    END IF;
END
$postcheck$;

COMMIT;
