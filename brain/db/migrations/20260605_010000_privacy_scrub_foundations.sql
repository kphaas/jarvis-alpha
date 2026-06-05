-- Migration: 20260605_010000_privacy_scrub_foundations
-- Purpose: Privacy-scrub P1 foundations. Inert, additive, FORCE-RLS protected,
--          and designed so raw identity/legal material is stored only in
--          encrypted payload columns.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relname = 'alpha_approval_queue'
          AND relnamespace = 'public'::regnamespace
    ) THEN
        RAISE EXCEPTION 'privacy-scrub requires public.alpha_approval_queue';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION public.privacy_encrypt_payload(
    p_text TEXT,
    p_key TEXT
)
RETURNS BYTEA
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
BEGIN
    IF p_text IS NULL THEN
        RETURN NULL;
    END IF;
    IF COALESCE(p_key, '') = '' THEN
        RAISE EXCEPTION 'privacy encryption key is required';
    END IF;
    RETURN pgp_sym_encrypt(
        p_text,
        p_key,
        'compress-algo=1, cipher-algo=aes256'
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.privacy_scrub_touch_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS public.alpha_privacy_subjects (
    id                           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                      TEXT NOT NULL,
    display_label_digest          TEXT NOT NULL,
    role                         TEXT NOT NULL
                                 CHECK (role IN ('adult', 'minor')),
    guardian_user_id             TEXT,
    jurisdiction                 TEXT NOT NULL DEFAULT 'US_GA',
    subject_payload_ciphertext    BYTEA NOT NULL,
    subject_payload_hash          TEXT NOT NULL,
    subject_payload_key_version   TEXT NOT NULL,
    status                       TEXT NOT NULL DEFAULT 'active'
                                 CHECK (status IN ('active', 'paused', 'archived')),
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT privacy_subject_minor_guardian_check
        CHECK (role <> 'minor' OR guardian_user_id IS NOT NULL),
    CONSTRAINT privacy_subject_label_digest_check
        CHECK (display_label_digest ~ '^hmac-sha256:[a-f0-9]{64}$'),
    CONSTRAINT privacy_subject_payload_hash_check
        CHECK (subject_payload_hash ~ '^sha256:[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_privacy_subjects_user
    ON public.alpha_privacy_subjects(user_id);
CREATE INDEX IF NOT EXISTS idx_privacy_subjects_guardian
    ON public.alpha_privacy_subjects(guardian_user_id)
    WHERE guardian_user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_privacy_subjects_status
    ON public.alpha_privacy_subjects(status);

ALTER TABLE public.alpha_privacy_subjects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_privacy_subjects FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_subjects_isolation
    ON public.alpha_privacy_subjects;
CREATE POLICY privacy_subjects_isolation
    ON public.alpha_privacy_subjects
    FOR ALL
    USING (
        user_id = current_setting('rls.user_id', true)
        OR guardian_user_id = current_setting('rls.user_id', true)
        OR current_setting('rls.role', true) = 'platform_admin'
    )
    WITH CHECK (
        user_id = current_setting('rls.user_id', true)
        OR guardian_user_id = current_setting('rls.user_id', true)
        OR current_setting('rls.role', true) = 'platform_admin'
    );

CREATE TABLE IF NOT EXISTS public.alpha_privacy_identity_tuples (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id          UUID NOT NULL
                       REFERENCES public.alpha_privacy_subjects(id)
                       ON DELETE RESTRICT,
    tuple_type          TEXT NOT NULL
                       CHECK (tuple_type IN (
                           'email', 'phone', 'address',
                           'name', 'full_name', 'dob'
                       )),
    digest              TEXT NOT NULL,
    key_version         TEXT NOT NULL,
    label_digest        TEXT,
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT privacy_identity_digest_check
        CHECK (digest ~ '^hmac-sha256:[a-f0-9]{64}$'),
    CONSTRAINT privacy_identity_label_digest_check
        CHECK (label_digest IS NULL OR label_digest ~ '^hmac-sha256:[a-f0-9]{64}$'),
    CONSTRAINT uq_privacy_subject_tuple_digest
        UNIQUE (subject_id, tuple_type, digest, key_version)
);

CREATE INDEX IF NOT EXISTS idx_privacy_tuples_subject
    ON public.alpha_privacy_identity_tuples(subject_id);
CREATE INDEX IF NOT EXISTS idx_privacy_tuples_digest
    ON public.alpha_privacy_identity_tuples(digest);

ALTER TABLE public.alpha_privacy_identity_tuples ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_privacy_identity_tuples FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_tuples_isolation
    ON public.alpha_privacy_identity_tuples;
CREATE POLICY privacy_tuples_isolation
    ON public.alpha_privacy_identity_tuples
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

CREATE TABLE IF NOT EXISTS public.alpha_privacy_targets_cache (
    id                            TEXT PRIMARY KEY,
    name                          TEXT NOT NULL,
    category                      TEXT NOT NULL
                                  CHECK (category IN (
                                      'data_broker', 'social',
                                      'public_record', 'breach_db'
                                  )),
    jurisdiction                  TEXT NOT NULL,
    opt_out_method                TEXT NOT NULL
                                  CHECK (opt_out_method IN (
                                      'email', 'web_form', 'api',
                                      'manual_only', 'court_motion'
                                  )),
    opt_out_url                   TEXT,
    contact_email                 TEXT,
    supports_minors               BOOLEAN NOT NULL DEFAULT FALSE,
    requires_sensitive_payload    BOOLEAN NOT NULL DEFAULT FALSE,
    requires_identity_document    BOOLEAN NOT NULL DEFAULT FALSE,
    avg_response_days             INTEGER,
    last_verified                 DATE,
    notes                         TEXT,
    yaml_source                   TEXT NOT NULL,
    loaded_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_privacy_targets_category
    ON public.alpha_privacy_targets_cache(category);
CREATE INDEX IF NOT EXISTS idx_privacy_targets_jurisdiction
    ON public.alpha_privacy_targets_cache(jurisdiction);

CREATE TABLE IF NOT EXISTS public.alpha_privacy_scans (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id                  UUID NOT NULL
                               REFERENCES public.alpha_privacy_subjects(id)
                               ON DELETE RESTRICT,
    scan_type                   TEXT NOT NULL
                               CHECK (scan_type IN (
                                   'local', 'external_broker', 'external_social',
                                   'external_public_record', 'external_breach'
                               )),
    status                      TEXT NOT NULL DEFAULT 'pending'
                               CHECK (status IN (
                                   'pending', 'running', 'completed', 'failed'
                               )),
    query_payload_ciphertext     BYTEA,
    query_payload_hash           TEXT,
    payload_key_version          TEXT,
    started_at                  TIMESTAMPTZ,
    completed_at                TIMESTAMPTZ,
    error_code                  TEXT,
    error_digest                TEXT,
    results_count               INTEGER NOT NULL DEFAULT 0,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT privacy_scan_query_hash_check
        CHECK (query_payload_hash IS NULL OR query_payload_hash ~ '^sha256:[a-f0-9]{64}$'),
    CONSTRAINT privacy_scan_error_digest_check
        CHECK (error_digest IS NULL OR error_digest ~ '^sha256:[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_privacy_scans_subject
    ON public.alpha_privacy_scans(subject_id);
CREATE INDEX IF NOT EXISTS idx_privacy_scans_status
    ON public.alpha_privacy_scans(status);
CREATE INDEX IF NOT EXISTS idx_privacy_scans_created
    ON public.alpha_privacy_scans(created_at DESC);

ALTER TABLE public.alpha_privacy_scans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_privacy_scans FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_scans_isolation
    ON public.alpha_privacy_scans;
CREATE POLICY privacy_scans_isolation
    ON public.alpha_privacy_scans
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

CREATE TABLE IF NOT EXISTS public.alpha_privacy_discoveries (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_id                    UUID NOT NULL
                               REFERENCES public.alpha_privacy_scans(id)
                               ON DELETE RESTRICT,
    subject_id                  UUID NOT NULL
                               REFERENCES public.alpha_privacy_subjects(id)
                               ON DELETE RESTRICT,
    target_id                  TEXT NOT NULL
                               REFERENCES public.alpha_privacy_targets_cache(id),
    match_confidence           REAL NOT NULL
                               CHECK (match_confidence >= 0 AND match_confidence <= 1),
    match_url_digest           TEXT,
    match_payload_ciphertext    BYTEA,
    match_payload_hash          TEXT,
    payload_key_version         TEXT,
    status                     TEXT NOT NULL DEFAULT 'new'
                               CHECK (status IN (
                                   'new', 'confirmed', 'dismissed', 'superseded'
                               )),
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT privacy_discovery_url_digest_check
        CHECK (match_url_digest IS NULL OR match_url_digest ~ '^hmac-sha256:[a-f0-9]{64}$'),
    CONSTRAINT privacy_discovery_payload_hash_check
        CHECK (match_payload_hash IS NULL OR match_payload_hash ~ '^sha256:[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_privacy_discoveries_scan
    ON public.alpha_privacy_discoveries(scan_id);
CREATE INDEX IF NOT EXISTS idx_privacy_discoveries_subject
    ON public.alpha_privacy_discoveries(subject_id);
CREATE INDEX IF NOT EXISTS idx_privacy_discoveries_status
    ON public.alpha_privacy_discoveries(status);

ALTER TABLE public.alpha_privacy_discoveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_privacy_discoveries FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_discoveries_isolation
    ON public.alpha_privacy_discoveries;
CREATE POLICY privacy_discoveries_isolation
    ON public.alpha_privacy_discoveries
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

CREATE TABLE IF NOT EXISTS public.alpha_privacy_actions (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id                  UUID NOT NULL
                               REFERENCES public.alpha_privacy_subjects(id)
                               ON DELETE RESTRICT,
    target_id                  TEXT NOT NULL
                               REFERENCES public.alpha_privacy_targets_cache(id),
    discovery_id               UUID
                               REFERENCES public.alpha_privacy_discoveries(id),
    action_type                TEXT NOT NULL
                               CHECK (action_type IN (
                                   'scan_local', 'scan_external', 'draft',
                                   'send_opt_out', 'file_motion', 'verify'
                               )),
    approval_tier              TEXT NOT NULL
                               CHECK (approval_tier IN ('T1', 'T2', 'T3', 'T4', 'T5')),
    status                     TEXT NOT NULL DEFAULT 'pending'
                               CHECK (status IN (
                                   'pending', 'awaiting_approval', 'approved',
                                   'sent', 'confirmed', 'rejected',
                                   'expired', 'failed'
                               )),
    draft_payload_ciphertext    BYTEA,
    draft_payload_hash          TEXT,
    metadata_ciphertext         BYTEA,
    metadata_hash               TEXT,
    payload_key_version         TEXT,
    sent_at                    TIMESTAMPTZ,
    confirmed_at               TIMESTAMPTZ,
    verification_due_at        TIMESTAMPTZ,
    approval_queue_id          UUID
                               REFERENCES public.alpha_approval_queue(id),
    error_code                 TEXT,
    error_digest               TEXT,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT privacy_action_draft_hash_check
        CHECK (draft_payload_hash IS NULL OR draft_payload_hash ~ '^sha256:[a-f0-9]{64}$'),
    CONSTRAINT privacy_action_metadata_hash_check
        CHECK (metadata_hash IS NULL OR metadata_hash ~ '^sha256:[a-f0-9]{64}$'),
    CONSTRAINT privacy_action_error_digest_check
        CHECK (error_digest IS NULL OR error_digest ~ '^sha256:[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_privacy_actions_subject
    ON public.alpha_privacy_actions(subject_id);
CREATE INDEX IF NOT EXISTS idx_privacy_actions_status
    ON public.alpha_privacy_actions(status);
CREATE INDEX IF NOT EXISTS idx_privacy_actions_approval
    ON public.alpha_privacy_actions(approval_queue_id)
    WHERE approval_queue_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_privacy_actions_verification_due
    ON public.alpha_privacy_actions(verification_due_at)
    WHERE status = 'sent';

ALTER TABLE public.alpha_privacy_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_privacy_actions FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_actions_isolation
    ON public.alpha_privacy_actions;
CREATE POLICY privacy_actions_isolation
    ON public.alpha_privacy_actions
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

CREATE TABLE IF NOT EXISTS public.alpha_privacy_action_events (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action_id                  UUID NOT NULL
                               REFERENCES public.alpha_privacy_actions(id)
                               ON DELETE RESTRICT,
    event_type                 TEXT NOT NULL
                               CHECK (event_type IN (
                                   'created', 'approval_requested', 'approved',
                                   'rejected', 'sent', 'confirmed', 'failed',
                                   'verification_scheduled', 'note'
                               )),
    actor                      TEXT NOT NULL,
    event_payload_ciphertext    BYTEA,
    event_payload_hash          TEXT,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT privacy_action_event_payload_hash_check
        CHECK (event_payload_hash IS NULL OR event_payload_hash ~ '^sha256:[a-f0-9]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_privacy_action_events_action
    ON public.alpha_privacy_action_events(action_id, created_at);

ALTER TABLE public.alpha_privacy_action_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_privacy_action_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS privacy_action_events_isolation
    ON public.alpha_privacy_action_events;
CREATE POLICY privacy_action_events_isolation
    ON public.alpha_privacy_action_events
    FOR ALL
    USING (
        action_id IN (
            SELECT action.id
            FROM public.alpha_privacy_actions AS action
            JOIN public.alpha_privacy_subjects AS subject
              ON subject.id = action.subject_id
            WHERE subject.user_id = current_setting('rls.user_id', true)
               OR subject.guardian_user_id = current_setting('rls.user_id', true)
               OR current_setting('rls.role', true) = 'platform_admin'
        )
    )
    WITH CHECK (
        action_id IN (
            SELECT action.id
            FROM public.alpha_privacy_actions AS action
            JOIN public.alpha_privacy_subjects AS subject
              ON subject.id = action.subject_id
            WHERE subject.user_id = current_setting('rls.user_id', true)
               OR subject.guardian_user_id = current_setting('rls.user_id', true)
               OR current_setting('rls.role', true) = 'platform_admin'
        )
    );

CREATE OR REPLACE FUNCTION public.privacy_action_events_append_only()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    RAISE EXCEPTION 'alpha_privacy_action_events is append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_privacy_action_events_no_update
    ON public.alpha_privacy_action_events;
CREATE TRIGGER trg_privacy_action_events_no_update
    BEFORE UPDATE ON public.alpha_privacy_action_events
    FOR EACH ROW
    EXECUTE FUNCTION public.privacy_action_events_append_only();

DROP TRIGGER IF EXISTS trg_privacy_action_events_no_delete
    ON public.alpha_privacy_action_events;
CREATE TRIGGER trg_privacy_action_events_no_delete
    BEFORE DELETE ON public.alpha_privacy_action_events
    FOR EACH ROW
    EXECUTE FUNCTION public.privacy_action_events_append_only();

CREATE OR REPLACE FUNCTION public.privacy_enforce_action_tier()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_role TEXT;
BEGIN
    SELECT role INTO v_role
    FROM public.alpha_privacy_subjects
    WHERE id = NEW.subject_id;

    IF v_role IS NULL THEN
        RAISE EXCEPTION 'privacy action subject not found: %', NEW.subject_id;
    END IF;

    IF NEW.action_type = 'file_motion' AND NEW.approval_tier <> 'T5' THEN
        RAISE EXCEPTION 'file_motion requires T5 approval';
    END IF;

    IF v_role = 'minor'
       AND NEW.action_type IN ('send_opt_out', 'scan_external', 'verify')
       AND NEW.approval_tier <> 'T5' THEN
        RAISE EXCEPTION 'minor external privacy actions require T5 approval';
    END IF;

    IF NEW.action_type IN ('send_opt_out', 'scan_external', 'verify')
       AND NEW.approval_tier IN ('T1', 'T2', 'T3') THEN
        RAISE EXCEPTION '% requires at least T4 approval', NEW.action_type;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_privacy_actions_enforce_tier
    ON public.alpha_privacy_actions;
CREATE TRIGGER trg_privacy_actions_enforce_tier
    BEFORE INSERT OR UPDATE OF action_type, approval_tier, subject_id
    ON public.alpha_privacy_actions
    FOR EACH ROW
    EXECUTE FUNCTION public.privacy_enforce_action_tier();

DROP TRIGGER IF EXISTS trg_privacy_subjects_updated_at
    ON public.alpha_privacy_subjects;
CREATE TRIGGER trg_privacy_subjects_updated_at
    BEFORE UPDATE ON public.alpha_privacy_subjects
    FOR EACH ROW
    EXECUTE FUNCTION public.privacy_scrub_touch_updated_at();

DROP TRIGGER IF EXISTS trg_privacy_discoveries_updated_at
    ON public.alpha_privacy_discoveries;
CREATE TRIGGER trg_privacy_discoveries_updated_at
    BEFORE UPDATE ON public.alpha_privacy_discoveries
    FOR EACH ROW
    EXECUTE FUNCTION public.privacy_scrub_touch_updated_at();

DROP TRIGGER IF EXISTS trg_privacy_actions_updated_at
    ON public.alpha_privacy_actions;
CREATE TRIGGER trg_privacy_actions_updated_at
    BEFORE UPDATE ON public.alpha_privacy_actions
    FOR EACH ROW
    EXECUTE FUNCTION public.privacy_scrub_touch_updated_at();

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_privacy_subjects,
               public.alpha_privacy_identity_tuples,
               public.alpha_privacy_scans,
               public.alpha_privacy_discoveries,
               public.alpha_privacy_actions
            TO jarvis_alpha_app;
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON public.alpha_privacy_targets_cache
            TO jarvis_alpha_app;
        GRANT SELECT, INSERT
            ON public.alpha_privacy_action_events
            TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.privacy_encrypt_payload(TEXT, TEXT)
            TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT SELECT, INSERT, UPDATE
            ON public.alpha_privacy_subjects,
               public.alpha_privacy_identity_tuples,
               public.alpha_privacy_scans,
               public.alpha_privacy_discoveries,
               public.alpha_privacy_actions
            TO jarvis_alpha_writer;
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON public.alpha_privacy_targets_cache
            TO jarvis_alpha_writer;
        GRANT SELECT, INSERT
            ON public.alpha_privacy_action_events
            TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.privacy_encrypt_payload(TEXT, TEXT)
            TO jarvis_alpha_writer;
    END IF;
END $$;

COMMENT ON TABLE public.alpha_privacy_subjects IS
    'Privacy-scrub subjects. Display names, DOBs, notes, and legal details live only in encrypted payloads.';
COMMENT ON TABLE public.alpha_privacy_action_events IS
    'Append-only audit evidence for privacy-scrub actions.';

DO $$
DECLARE
    v_blob BYTEA;
    v_plain TEXT;
    v_subject UUID;
    v_target TEXT := 'postflight_target';
    v_rejected BOOLEAN := FALSE;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    PERFORM set_config('rls.user_id', 'postflight', true);

    v_blob := public.privacy_encrypt_payload('postflight payload', 'postflight-key');
    v_plain := pgp_sym_decrypt(v_blob, 'postflight-key');
    IF v_plain <> 'postflight payload' THEN
        RAISE EXCEPTION 'privacy_encrypt_payload roundtrip failed';
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
        RAISE EXCEPTION 'privacy decrypt/read helper must not exist in P1';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relname IN (
            'alpha_privacy_subjects',
            'alpha_privacy_identity_tuples',
            'alpha_privacy_scans',
            'alpha_privacy_discoveries',
            'alpha_privacy_actions',
            'alpha_privacy_action_events'
        )
        AND NOT (relrowsecurity AND relforcerowsecurity)
    ) THEN
        RAISE EXCEPTION 'privacy-scrub FORCE RLS postflight failed';
    END IF;

    INSERT INTO public.alpha_privacy_targets_cache (
        id, name, category, jurisdiction, opt_out_method,
        yaml_source
    )
    VALUES (
        v_target, 'Postflight Target', 'data_broker', 'US_FEDERAL',
        'web_form', 'postflight'
    )
    ON CONFLICT (id) DO NOTHING;

    INSERT INTO public.alpha_privacy_subjects (
        user_id, display_label_digest, role, guardian_user_id,
        subject_payload_ciphertext, subject_payload_hash,
        subject_payload_key_version
    )
    VALUES (
        'postflight', 'hmac-sha256:0000000000000000000000000000000000000000000000000000000000000000',
        'minor', 'postflight',
        v_blob, 'sha256:0000000000000000000000000000000000000000000000000000000000000000',
        'postflight'
    )
    RETURNING id INTO v_subject;

    BEGIN
        INSERT INTO public.alpha_privacy_actions (
            subject_id, target_id, action_type, approval_tier
        )
        VALUES (v_subject, v_target, 'send_opt_out', 'T4');
    EXCEPTION
        WHEN raise_exception THEN
            v_rejected := TRUE;
    END;

    IF NOT v_rejected THEN
        RAISE EXCEPTION 'minor T4 send_opt_out should have failed';
    END IF;

    DELETE FROM public.alpha_privacy_subjects
    WHERE id = v_subject;
    DELETE FROM public.alpha_privacy_targets_cache
    WHERE id = v_target;
END $$;

COMMIT;
