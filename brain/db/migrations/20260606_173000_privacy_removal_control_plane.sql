-- Purpose: P4 privacy removal control plane.
-- Adds authorization, adapter, evidence, recurrence, search deindex, and
-- public-record triage metadata. This migration is additive and does not
-- create outbound broker submission behavior.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260606173000);

DO $preflight$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'alpha_privacy_subjects'
    ) THEN
        RAISE EXCEPTION 'privacy removal control preflight failed; subjects table missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'alpha_privacy_targets_cache'
    ) THEN
        RAISE EXCEPTION 'privacy removal control preflight failed; target cache missing';
    END IF;
END
$preflight$;

CREATE TABLE IF NOT EXISTS public.alpha_privacy_authorizations (
    id                                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id                          UUID NOT NULL
                                        REFERENCES public.alpha_privacy_subjects(id)
                                        ON DELETE RESTRICT,
    authorization_type                  TEXT NOT NULL
                                        CHECK (authorization_type IN (
                                            'agent_authorization',
                                            'guardian_authorization',
                                            'custom_removal',
                                            'search_deindex',
                                            'public_record_triage'
                                        )),
    status                              TEXT NOT NULL DEFAULT 'draft'
                                        CHECK (status IN (
                                            'draft', 'active', 'revoked', 'expired'
                                        )),
    created_by_user_id                  TEXT NOT NULL,
    authorization_payload_ciphertext     BYTEA NOT NULL,
    authorization_payload_hash           TEXT NOT NULL,
    payload_key_version                 TEXT NOT NULL,
    expires_at                          TIMESTAMPTZ,
    revoked_at                          TIMESTAMPTZ,
    created_at                          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT privacy_authorization_payload_hash_check
        CHECK (authorization_payload_hash ~ '^sha256:[a-f0-9]{64}$'),
    CONSTRAINT privacy_authorization_revoked_status_check
        CHECK (revoked_at IS NULL OR status = 'revoked')
);

CREATE INDEX IF NOT EXISTS idx_privacy_authorizations_subject
    ON public.alpha_privacy_authorizations(subject_id);
CREATE INDEX IF NOT EXISTS idx_privacy_authorizations_status
    ON public.alpha_privacy_authorizations(status);
CREATE INDEX IF NOT EXISTS idx_privacy_authorizations_expiry
    ON public.alpha_privacy_authorizations(expires_at)
    WHERE expires_at IS NOT NULL;

ALTER TABLE public.alpha_privacy_authorizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_privacy_authorizations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_authorizations_isolation
    ON public.alpha_privacy_authorizations;
CREATE POLICY privacy_authorizations_isolation
    ON public.alpha_privacy_authorizations
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

CREATE TABLE IF NOT EXISTS public.alpha_privacy_adapter_profiles (
    target_id                         TEXT PRIMARY KEY
                                      REFERENCES public.alpha_privacy_targets_cache(id)
                                      ON DELETE RESTRICT,
    adapter_kind                      TEXT NOT NULL
                                      CHECK (adapter_kind IN (
                                          'manual',
                                          'web_form',
                                          'email',
                                          'api',
                                          'postal',
                                          'search_deindex',
                                          'court_triage'
                                      )),
    coverage_lane                     TEXT NOT NULL
                                      CHECK (coverage_lane IN (
                                          'broker',
                                          'custom',
                                          'search',
                                          'public_record'
                                      )),
    automation_level                  TEXT NOT NULL DEFAULT 'draft_only'
                                      CHECK (automation_level IN (
                                          'draft_only',
                                          'operator_assisted',
                                          'approval_ready',
                                          'live_disabled'
                                      )),
    risk_tier                         TEXT NOT NULL DEFAULT 'T4'
                                      CHECK (risk_tier IN ('T2', 'T3', 'T4', 'T5')),
    requires_authorization            BOOLEAN NOT NULL DEFAULT TRUE,
    requires_identity_document        BOOLEAN NOT NULL DEFAULT FALSE,
    requires_captcha_handoff          BOOLEAN NOT NULL DEFAULT FALSE,
    supports_recurring_monitor        BOOLEAN NOT NULL DEFAULT TRUE,
    sla_days                          INTEGER CHECK (sla_days IS NULL OR sla_days > 0),
    instructions_payload_hash          TEXT,
    payload_key_version               TEXT,
    created_at                        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT privacy_adapter_instructions_hash_check
        CHECK (
            instructions_payload_hash IS NULL
            OR instructions_payload_hash ~ '^sha256:[a-f0-9]{64}$'
        )
);

CREATE INDEX IF NOT EXISTS idx_privacy_adapter_profiles_lane
    ON public.alpha_privacy_adapter_profiles(coverage_lane);
CREATE INDEX IF NOT EXISTS idx_privacy_adapter_profiles_monitor
    ON public.alpha_privacy_adapter_profiles(supports_recurring_monitor)
    WHERE supports_recurring_monitor;

ALTER TABLE public.alpha_privacy_adapter_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_privacy_adapter_profiles FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_adapter_profiles_read
    ON public.alpha_privacy_adapter_profiles;
CREATE POLICY privacy_adapter_profiles_read
    ON public.alpha_privacy_adapter_profiles
    FOR SELECT
    USING (
        current_setting('rls.user_id', true) <> ''
        OR current_setting('rls.role', true) = 'platform_admin'
    );

DROP POLICY IF EXISTS privacy_adapter_profiles_admin_write
    ON public.alpha_privacy_adapter_profiles;
CREATE POLICY privacy_adapter_profiles_admin_write
    ON public.alpha_privacy_adapter_profiles
    FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

INSERT INTO public.alpha_privacy_adapter_profiles (
    target_id,
    adapter_kind,
    coverage_lane,
    automation_level,
    risk_tier,
    requires_identity_document,
    supports_recurring_monitor,
    sla_days
)
SELECT
    target.id,
    CASE target.opt_out_method
        WHEN 'web_form' THEN 'web_form'
        WHEN 'email' THEN 'email'
        WHEN 'api' THEN 'api'
        WHEN 'court_motion' THEN 'court_triage'
        ELSE 'manual'
    END,
    CASE target.category
        WHEN 'public_record' THEN 'public_record'
        ELSE 'broker'
    END,
    'draft_only',
    CASE
        WHEN target.category = 'public_record' OR target.opt_out_method = 'court_motion'
            THEN 'T5'
        WHEN target.requires_identity_document
            THEN 'T4'
        ELSE 'T3'
    END,
    target.requires_identity_document,
    target.category <> 'public_record',
    target.avg_response_days
FROM public.alpha_privacy_targets_cache AS target
ON CONFLICT (target_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.alpha_privacy_evidence_items (
    id                             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id                     UUID NOT NULL
                                   REFERENCES public.alpha_privacy_subjects(id)
                                   ON DELETE RESTRICT,
    target_id                      TEXT NOT NULL
                                   REFERENCES public.alpha_privacy_targets_cache(id)
                                   ON DELETE RESTRICT,
    action_id                      UUID
                                   REFERENCES public.alpha_privacy_actions(id)
                                   ON DELETE RESTRICT,
    evidence_type                  TEXT NOT NULL
                                   CHECK (evidence_type IN (
                                       'source_snapshot',
                                       'work_receipt',
                                       'broker_reply',
                                       'before_after',
                                       'verification',
                                       'search_result',
                                       'court_record'
                                   )),
    status                         TEXT NOT NULL DEFAULT 'captured'
                                   CHECK (status IN (
                                       'captured', 'reviewed', 'rejected', 'archived'
                                   )),
    evidence_payload_ciphertext     BYTEA NOT NULL,
    evidence_payload_hash           TEXT NOT NULL,
    payload_key_version            TEXT NOT NULL,
    captured_by_user_id            TEXT NOT NULL,
    captured_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT privacy_evidence_payload_hash_check
        CHECK (evidence_payload_hash ~ '^sha256:[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_privacy_evidence_subject
    ON public.alpha_privacy_evidence_items(subject_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_privacy_evidence_action
    ON public.alpha_privacy_evidence_items(action_id)
    WHERE action_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_privacy_evidence_target
    ON public.alpha_privacy_evidence_items(target_id);

ALTER TABLE public.alpha_privacy_evidence_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_privacy_evidence_items FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_evidence_items_isolation
    ON public.alpha_privacy_evidence_items;
CREATE POLICY privacy_evidence_items_isolation
    ON public.alpha_privacy_evidence_items
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

CREATE TABLE IF NOT EXISTS public.alpha_privacy_monitor_runs (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id                  UUID NOT NULL
                               REFERENCES public.alpha_privacy_subjects(id)
                               ON DELETE RESTRICT,
    run_type                    TEXT NOT NULL
                               CHECK (run_type IN (
                                   'discovery',
                                   'recurring_broker',
                                   'search_deindex',
                                   'public_record'
                               )),
    status                      TEXT NOT NULL DEFAULT 'scheduled'
                               CHECK (status IN (
                                   'scheduled',
                                   'running',
                                   'completed',
                                   'blocked',
                                   'failed'
                               )),
    scheduled_for               TIMESTAMPTZ NOT NULL,
    started_at                  TIMESTAMPTZ,
    completed_at                TIMESTAMPTZ,
    coverage_count              INTEGER NOT NULL DEFAULT 0
                               CHECK (coverage_count >= 0),
    actionable_count            INTEGER NOT NULL DEFAULT 0
                               CHECK (actionable_count >= 0),
    reappeared_count            INTEGER NOT NULL DEFAULT 0
                               CHECK (reappeared_count >= 0),
    report_payload_ciphertext    BYTEA,
    report_payload_hash          TEXT,
    payload_key_version         TEXT,
    created_by_user_id          TEXT NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT privacy_monitor_report_hash_check
        CHECK (report_payload_hash IS NULL OR report_payload_hash ~ '^sha256:[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_privacy_monitor_runs_subject
    ON public.alpha_privacy_monitor_runs(subject_id, scheduled_for DESC);
CREATE INDEX IF NOT EXISTS idx_privacy_monitor_runs_status
    ON public.alpha_privacy_monitor_runs(status, scheduled_for);

ALTER TABLE public.alpha_privacy_monitor_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_privacy_monitor_runs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_monitor_runs_isolation
    ON public.alpha_privacy_monitor_runs;
CREATE POLICY privacy_monitor_runs_isolation
    ON public.alpha_privacy_monitor_runs
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

CREATE TABLE IF NOT EXISTS public.alpha_privacy_search_deindex_items (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id                  UUID NOT NULL
                               REFERENCES public.alpha_privacy_subjects(id)
                               ON DELETE RESTRICT,
    target_id                  TEXT
                               REFERENCES public.alpha_privacy_targets_cache(id)
                               ON DELETE RESTRICT,
    search_provider             TEXT NOT NULL
                               CHECK (search_provider IN ('google', 'bing', 'other')),
    result_url_digest           TEXT NOT NULL,
    legal_basis                 TEXT NOT NULL DEFAULT 'privacy_or_outdated_content'
                               CHECK (legal_basis IN (
                                   'privacy_or_outdated_content',
                                   'exposed_personal_information',
                                   'minor_safety',
                                   'court_order_required'
                               )),
    status                      TEXT NOT NULL DEFAULT 'needs_review'
                               CHECK (status IN (
                                   'needs_review',
                                   'queued',
                                   'submitted',
                                   'removed',
                                   'not_applicable',
                                   'blocked'
                               )),
    item_payload_ciphertext      BYTEA NOT NULL,
    item_payload_hash            TEXT NOT NULL,
    payload_key_version         TEXT NOT NULL,
    last_checked_at             TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT privacy_search_url_digest_check
        CHECK (result_url_digest ~ '^hmac-sha256:[a-f0-9]{64}$'),
    CONSTRAINT privacy_search_payload_hash_check
        CHECK (item_payload_hash ~ '^sha256:[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_privacy_search_subject
    ON public.alpha_privacy_search_deindex_items(subject_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_privacy_search_status
    ON public.alpha_privacy_search_deindex_items(status);

ALTER TABLE public.alpha_privacy_search_deindex_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_privacy_search_deindex_items FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_search_deindex_items_isolation
    ON public.alpha_privacy_search_deindex_items;
CREATE POLICY privacy_search_deindex_items_isolation
    ON public.alpha_privacy_search_deindex_items
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

CREATE TABLE IF NOT EXISTS public.alpha_privacy_public_record_triage (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id                  UUID NOT NULL
                               REFERENCES public.alpha_privacy_subjects(id)
                               ON DELETE RESTRICT,
    target_id                  TEXT
                               REFERENCES public.alpha_privacy_targets_cache(id)
                               ON DELETE RESTRICT,
    jurisdiction                TEXT NOT NULL,
    record_kind                 TEXT NOT NULL
                               CHECK (record_kind IN (
                                   'court_record',
                                   'property_record',
                                   'voter_record',
                                   'professional_license',
                                   'other'
                               )),
    triage_status               TEXT NOT NULL DEFAULT 'needs_review'
                               CHECK (triage_status IN (
                                   'needs_review',
                                   'broker_copy',
                                   'deindex_candidate',
                                   'legal_review_required',
                                   'not_actionable',
                                   'blocked'
                               )),
    legal_process_required      BOOLEAN NOT NULL DEFAULT FALSE,
    triage_payload_ciphertext    BYTEA NOT NULL,
    triage_payload_hash          TEXT NOT NULL,
    payload_key_version         TEXT NOT NULL,
    created_by_user_id          TEXT NOT NULL,
    reviewed_at                 TIMESTAMPTZ,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT privacy_public_record_payload_hash_check
        CHECK (triage_payload_hash ~ '^sha256:[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_privacy_public_record_subject
    ON public.alpha_privacy_public_record_triage(subject_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_privacy_public_record_status
    ON public.alpha_privacy_public_record_triage(triage_status);
CREATE INDEX IF NOT EXISTS idx_privacy_public_record_legal
    ON public.alpha_privacy_public_record_triage(legal_process_required)
    WHERE legal_process_required;

ALTER TABLE public.alpha_privacy_public_record_triage ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_privacy_public_record_triage FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_public_record_triage_isolation
    ON public.alpha_privacy_public_record_triage;
CREATE POLICY privacy_public_record_triage_isolation
    ON public.alpha_privacy_public_record_triage
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

DROP TRIGGER IF EXISTS trg_privacy_authorizations_updated_at
    ON public.alpha_privacy_authorizations;
CREATE TRIGGER trg_privacy_authorizations_updated_at
    BEFORE UPDATE ON public.alpha_privacy_authorizations
    FOR EACH ROW
    EXECUTE FUNCTION public.privacy_scrub_touch_updated_at();

DROP TRIGGER IF EXISTS trg_privacy_adapter_profiles_updated_at
    ON public.alpha_privacy_adapter_profiles;
CREATE TRIGGER trg_privacy_adapter_profiles_updated_at
    BEFORE UPDATE ON public.alpha_privacy_adapter_profiles
    FOR EACH ROW
    EXECUTE FUNCTION public.privacy_scrub_touch_updated_at();

DROP TRIGGER IF EXISTS trg_privacy_monitor_runs_updated_at
    ON public.alpha_privacy_monitor_runs;
CREATE TRIGGER trg_privacy_monitor_runs_updated_at
    BEFORE UPDATE ON public.alpha_privacy_monitor_runs
    FOR EACH ROW
    EXECUTE FUNCTION public.privacy_scrub_touch_updated_at();

DROP TRIGGER IF EXISTS trg_privacy_search_deindex_items_updated_at
    ON public.alpha_privacy_search_deindex_items;
CREATE TRIGGER trg_privacy_search_deindex_items_updated_at
    BEFORE UPDATE ON public.alpha_privacy_search_deindex_items
    FOR EACH ROW
    EXECUTE FUNCTION public.privacy_scrub_touch_updated_at();

DROP TRIGGER IF EXISTS trg_privacy_public_record_triage_updated_at
    ON public.alpha_privacy_public_record_triage;
CREATE TRIGGER trg_privacy_public_record_triage_updated_at
    BEFORE UPDATE ON public.alpha_privacy_public_record_triage
    FOR EACH ROW
    EXECUTE FUNCTION public.privacy_scrub_touch_updated_at();

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_privacy_authorizations,
               public.alpha_privacy_evidence_items,
               public.alpha_privacy_monitor_runs,
               public.alpha_privacy_search_deindex_items,
               public.alpha_privacy_public_record_triage
            TO jarvis_alpha_app;
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_privacy_adapter_profiles
            TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_privacy_authorizations,
               public.alpha_privacy_evidence_items,
               public.alpha_privacy_monitor_runs,
               public.alpha_privacy_search_deindex_items,
               public.alpha_privacy_public_record_triage
            TO jarvis_alpha_writer;
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_privacy_adapter_profiles
            TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON TABLE public.alpha_privacy_authorizations IS
    'Encrypted authorization artifacts for privacy removal work.';
COMMENT ON TABLE public.alpha_privacy_adapter_profiles IS
    'Local adapter metadata for broker, search, and public-record handling.';
COMMENT ON TABLE public.alpha_privacy_evidence_items IS
    'Encrypted evidence references and hashes for privacy removal proof.';
COMMENT ON TABLE public.alpha_privacy_monitor_runs IS
    'Local recurrence schedule and result metadata for privacy follow-up work.';
COMMENT ON TABLE public.alpha_privacy_search_deindex_items IS
    'Encrypted search deindex candidates. URLs are stored as digests or encrypted payloads.';
COMMENT ON TABLE public.alpha_privacy_public_record_triage IS
    'Encrypted public-record triage entries. Legal filing is not automated.';

DO $postcheck$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relname IN (
            'alpha_privacy_authorizations',
            'alpha_privacy_adapter_profiles',
            'alpha_privacy_evidence_items',
            'alpha_privacy_monitor_runs',
            'alpha_privacy_search_deindex_items',
            'alpha_privacy_public_record_triage'
        )
        AND NOT (relrowsecurity AND relforcerowsecurity)
    ) THEN
        RAISE EXCEPTION 'privacy removal control FORCE RLS postcheck failed';
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
        RAISE EXCEPTION 'privacy removal control must not expose decrypt helpers';
    END IF;
END
$postcheck$;

COMMIT;
