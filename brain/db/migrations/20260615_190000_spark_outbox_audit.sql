-- Purpose: Encrypted Spark outbox and append-only audit events.
-- PR-1 stores exact approved draft text only as app-encrypted ciphertext. It
-- does not add any send executor or SQL decrypt function.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260615190000);

CREATE TABLE IF NOT EXISTS public.alpha_spark_outbox (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel                  TEXT NOT NULL
                             CHECK (channel IN ('imessage', 'email')),
    principal_id             TEXT NOT NULL,
    target_ref_hash          TEXT NOT NULL,
    target_label             TEXT NOT NULL,
    approval_queue_id        UUID NOT NULL
                             REFERENCES public.alpha_approval_queue(id),
    approval_parameters_hash TEXT NOT NULL,
    draft_text_ciphertext    BYTEA NOT NULL,
    draft_text_hash          TEXT NOT NULL,
    payload_key_version      TEXT NOT NULL,
    status                   TEXT NOT NULL DEFAULT 'pending_approval'
                             CHECK (status IN (
                                 'pending_approval', 'approved', 'send_ready',
                                 'sending', 'sent', 'send_failed', 'cancelled'
                             )),
    send_attempt_count       INTEGER NOT NULL DEFAULT 0
                             CHECK (send_attempt_count >= 0),
    last_error_class         TEXT,
    last_error_message       TEXT,
    created_by               TEXT NOT NULL,
    created_actor_type       TEXT NOT NULL,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at                  TIMESTAMPTZ,
    CONSTRAINT alpha_spark_outbox_principal_check
        CHECK (principal_id ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
    CONSTRAINT alpha_spark_outbox_target_label_check
        CHECK (char_length(btrim(target_label)) BETWEEN 1 AND 160),
    CONSTRAINT alpha_spark_outbox_parameters_hash_check
        CHECK (approval_parameters_hash ~ '^[a-f0-9]{64}$'),
    CONSTRAINT alpha_spark_outbox_draft_text_hash_check
        CHECK (draft_text_hash ~ '^(hmac-sha256|sha256):[a-f0-9]{64}$'),
    CONSTRAINT alpha_spark_outbox_ciphertext_check
        CHECK (octet_length(draft_text_ciphertext) >= 32),
    CONSTRAINT alpha_spark_outbox_payload_key_version_check
        CHECK (char_length(btrim(payload_key_version)) BETWEEN 1 AND 80),
    CONSTRAINT alpha_spark_outbox_created_by_check
        CHECK (char_length(btrim(created_by)) BETWEEN 1 AND 160),
    CONSTRAINT alpha_spark_outbox_actor_type_check
        CHECK (char_length(btrim(created_actor_type)) BETWEEN 1 AND 80),
    CONSTRAINT alpha_spark_outbox_unique_approval_text
        UNIQUE (approval_queue_id, draft_text_hash)
);

CREATE INDEX IF NOT EXISTS idx_alpha_spark_outbox_principal_status
    ON public.alpha_spark_outbox(principal_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alpha_spark_outbox_approval_queue
    ON public.alpha_spark_outbox(approval_queue_id);
CREATE INDEX IF NOT EXISTS idx_alpha_spark_outbox_channel_status
    ON public.alpha_spark_outbox(channel, status, created_at DESC);

CREATE TABLE IF NOT EXISTS public.alpha_spark_outbox_events (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    outbox_id     UUID NOT NULL REFERENCES public.alpha_spark_outbox(id),
    event_type    TEXT NOT NULL
                  CHECK (event_type IN (
                      'created', 'approval_synced', 'send_ready',
                      'sending', 'sent', 'send_failed', 'cancelled'
                  )),
    actor_sub     TEXT NOT NULL,
    actor_type    TEXT NOT NULL,
    event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_spark_outbox_events_actor_sub_check
        CHECK (char_length(btrim(actor_sub)) BETWEEN 1 AND 160),
    CONSTRAINT alpha_spark_outbox_events_actor_type_check
        CHECK (char_length(btrim(actor_type)) BETWEEN 1 AND 80),
    CONSTRAINT alpha_spark_outbox_events_payload_object_check
        CHECK (jsonb_typeof(event_payload) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_alpha_spark_outbox_events_outbox
    ON public.alpha_spark_outbox_events(outbox_id, created_at DESC);

CREATE OR REPLACE FUNCTION public.alpha_spark_outbox_events_immutable()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $$
BEGIN
    RAISE EXCEPTION 'alpha_spark_outbox_events is append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_alpha_spark_outbox_events_immutable
    ON public.alpha_spark_outbox_events;
CREATE TRIGGER trg_alpha_spark_outbox_events_immutable
    BEFORE UPDATE OR DELETE ON public.alpha_spark_outbox_events
    FOR EACH ROW EXECUTE FUNCTION public.alpha_spark_outbox_events_immutable();

ALTER TABLE public.alpha_spark_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_spark_outbox FORCE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_spark_outbox_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_spark_outbox_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS alpha_spark_outbox_admin_all
    ON public.alpha_spark_outbox;
CREATE POLICY alpha_spark_outbox_admin_all
    ON public.alpha_spark_outbox
    FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

DROP POLICY IF EXISTS alpha_spark_outbox_events_admin_all
    ON public.alpha_spark_outbox_events;
CREATE POLICY alpha_spark_outbox_events_admin_all
    ON public.alpha_spark_outbox_events
    FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

CREATE OR REPLACE FUNCTION public.create_spark_outbox_item(
    p_channel text,
    p_principal_id text,
    p_target_ref_hash text,
    p_target_label text,
    p_approval_queue_id uuid,
    p_approval_parameters_hash text,
    p_draft_text_ciphertext bytea,
    p_draft_text_hash text,
    p_payload_key_version text,
    p_created_by text,
    p_created_actor_type text,
    p_event_metadata jsonb DEFAULT '{}'::jsonb
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $$
DECLARE
    v_channel text := lower(btrim(p_channel));
    v_principal text := lower(btrim(p_principal_id));
    v_target_ref_hash text := btrim(p_target_ref_hash);
    v_target_label text := btrim(p_target_label);
    v_parameters_hash text := lower(btrim(p_approval_parameters_hash));
    v_draft_text_hash text := lower(btrim(p_draft_text_hash));
    v_payload_key_version text := btrim(p_payload_key_version);
    v_created_by text := btrim(p_created_by);
    v_actor_type text := btrim(p_created_actor_type);
    v_event_payload jsonb := COALESCE(p_event_metadata, '{}'::jsonb);
    v_outbox_id uuid;
    v_existing_status text;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    IF v_channel NOT IN ('imessage', 'email') THEN
        RETURN jsonb_build_object('created', false, 'reason', 'invalid_channel');
    END IF;
    IF v_principal !~ '^[a-z0-9][a-z0-9_-]{0,63}$' THEN
        RETURN jsonb_build_object('created', false, 'reason', 'invalid_principal');
    END IF;
    IF char_length(v_target_ref_hash) < 6 OR char_length(v_target_ref_hash) > 160 THEN
        RETURN jsonb_build_object('created', false, 'reason', 'invalid_target_ref_hash');
    END IF;
    IF char_length(v_target_label) < 1 OR char_length(v_target_label) > 160 THEN
        RETURN jsonb_build_object('created', false, 'reason', 'invalid_target_label');
    END IF;
    IF v_parameters_hash !~ '^[a-f0-9]{64}$' THEN
        RETURN jsonb_build_object('created', false, 'reason', 'invalid_approval_parameters_hash');
    END IF;
    IF p_draft_text_ciphertext IS NULL OR octet_length(p_draft_text_ciphertext) < 32 THEN
        RETURN jsonb_build_object('created', false, 'reason', 'invalid_ciphertext');
    END IF;
    IF v_draft_text_hash !~ '^(hmac-sha256|sha256):[a-f0-9]{64}$' THEN
        RETURN jsonb_build_object('created', false, 'reason', 'invalid_draft_text_hash');
    END IF;
    IF char_length(v_payload_key_version) < 1 OR char_length(v_payload_key_version) > 80 THEN
        RETURN jsonb_build_object('created', false, 'reason', 'invalid_payload_key_version');
    END IF;
    IF char_length(v_created_by) < 1 OR char_length(v_created_by) > 160 THEN
        RETURN jsonb_build_object('created', false, 'reason', 'invalid_created_by');
    END IF;
    IF char_length(v_actor_type) < 1 OR char_length(v_actor_type) > 80 THEN
        RETURN jsonb_build_object('created', false, 'reason', 'invalid_actor_type');
    END IF;
    IF jsonb_typeof(v_event_payload) <> 'object' THEN
        RETURN jsonb_build_object('created', false, 'reason', 'invalid_event_metadata');
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.alpha_approval_queue AS q
        WHERE q.id = p_approval_queue_id
    ) THEN
        RETURN jsonb_build_object('created', false, 'reason', 'approval_not_found');
    END IF;

    SELECT o.id, o.status
    INTO v_outbox_id, v_existing_status
    FROM public.alpha_spark_outbox AS o
    WHERE o.approval_queue_id = p_approval_queue_id
      AND o.draft_text_hash = v_draft_text_hash
    LIMIT 1;

    IF v_outbox_id IS NOT NULL THEN
        RETURN jsonb_build_object(
            'created', false,
            'reason', 'already_exists',
            'outbox_id', v_outbox_id,
            'status', v_existing_status
        );
    END IF;

    INSERT INTO public.alpha_spark_outbox (
        channel,
        principal_id,
        target_ref_hash,
        target_label,
        approval_queue_id,
        approval_parameters_hash,
        draft_text_ciphertext,
        draft_text_hash,
        payload_key_version,
        status,
        created_by,
        created_actor_type,
        updated_at
    )
    VALUES (
        v_channel,
        v_principal,
        v_target_ref_hash,
        v_target_label,
        p_approval_queue_id,
        v_parameters_hash,
        p_draft_text_ciphertext,
        v_draft_text_hash,
        v_payload_key_version,
        'pending_approval',
        v_created_by,
        v_actor_type,
        NOW()
    )
    RETURNING id INTO v_outbox_id;

    INSERT INTO public.alpha_spark_outbox_events (
        outbox_id,
        event_type,
        actor_sub,
        actor_type,
        event_payload
    )
    VALUES (
        v_outbox_id,
        'created',
        v_created_by,
        v_actor_type,
        v_event_payload
    );

    RETURN jsonb_build_object(
        'created', true,
        'outbox_id', v_outbox_id,
        'status', 'pending_approval'
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.list_spark_outbox_items(
    p_principal_id text,
    p_limit integer DEFAULT 25
)
RETURNS TABLE (
    id text,
    channel text,
    principal_id text,
    target_label text,
    approval_queue_id text,
    draft_text_hash text,
    status text,
    send_attempt_count integer,
    created_at timestamptz,
    updated_at timestamptz,
    sent_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $$
DECLARE
    v_principal text := lower(btrim(p_principal_id));
    v_limit integer := LEAST(GREATEST(COALESCE(p_limit, 25), 1), 100);
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    IF v_principal !~ '^[a-z0-9][a-z0-9_-]{0,63}$' THEN
        RETURN;
    END IF;

    RETURN QUERY
    SELECT
        o.id::text,
        o.channel,
        o.principal_id,
        o.target_label,
        o.approval_queue_id::text,
        o.draft_text_hash,
        o.status,
        o.send_attempt_count,
        o.created_at,
        o.updated_at,
        o.sent_at
    FROM public.alpha_spark_outbox AS o
    WHERE o.principal_id = v_principal
    ORDER BY o.created_at DESC
    LIMIT v_limit;
END;
$$;

REVOKE ALL ON FUNCTION public.create_spark_outbox_item(
    text, text, text, text, uuid, text, bytea, text, text, text, text, jsonb
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.list_spark_outbox_items(text, integer) FROM PUBLIC;

DO $owner$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvisbrain') THEN
        EXECUTE
            'ALTER FUNCTION public.create_spark_outbox_item'
            || '(text, text, text, text, uuid, text, bytea, text, text, text, text, jsonb) OWNER TO jarvisbrain';
        EXECUTE
            'ALTER FUNCTION public.list_spark_outbox_items'
            || '(text, integer) OWNER TO jarvisbrain';
        EXECUTE
            'ALTER FUNCTION public.alpha_spark_outbox_events_immutable'
            || '() OWNER TO jarvisbrain';
    END IF;
END
$owner$;

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT EXECUTE ON FUNCTION public.create_spark_outbox_item(
            text, text, text, text, uuid, text, bytea, text, text, text, text, jsonb
        ) TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.list_spark_outbox_items(
            text, integer
        ) TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT EXECUTE ON FUNCTION public.create_spark_outbox_item(
            text, text, text, text, uuid, text, bytea, text, text, text, text, jsonb
        ) TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.list_spark_outbox_items(
            text, integer
        ) TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON TABLE public.alpha_spark_outbox IS
    'Spark encrypted outbox. Stores exact approved draft text as app-encrypted ciphertext only; PR-1 does not send messages.';
COMMENT ON TABLE public.alpha_spark_outbox_events IS
    'Append-only Spark outbox audit events without raw message bodies or plaintext draft text.';
COMMENT ON FUNCTION public.create_spark_outbox_item(
    text, text, text, text, uuid, text, bytea, text, text, text, text, jsonb
) IS
    'Creates an encrypted Spark outbox item and append-only audit event. No send side effects.';
COMMENT ON FUNCTION public.list_spark_outbox_items(text, integer) IS
    'Lists Spark outbox metadata only. Ciphertext and plaintext draft bodies are not returned.';

DO $postcheck$
DECLARE
    v_not_forced integer;
    v_decrypt_helpers integer;
BEGIN
    SELECT count(*)::integer
    INTO v_not_forced
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname IN ('alpha_spark_outbox', 'alpha_spark_outbox_events')
      AND NOT c.relforcerowsecurity;

    IF COALESCE(v_not_forced, 0) <> 0 THEN
        RAISE EXCEPTION 'Spark outbox RLS FORCE postcheck failed';
    END IF;

    SELECT count(*)::integer
    INTO v_decrypt_helpers
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.proname ILIKE '%spark%outbox%decrypt%';

    IF COALESCE(v_decrypt_helpers, 0) <> 0 THEN
        RAISE EXCEPTION 'Spark outbox SQL decrypt helper is not allowed';
    END IF;
END
$postcheck$;

COMMIT;

-- Downgrade:
-- BEGIN;
-- DROP FUNCTION IF EXISTS public.list_spark_outbox_items(text, integer);
-- DROP FUNCTION IF EXISTS public.create_spark_outbox_item(
--     text, text, text, text, uuid, text, bytea, text, text, text, text, jsonb
-- );
-- DROP TRIGGER IF EXISTS trg_alpha_spark_outbox_events_immutable
--     ON public.alpha_spark_outbox_events;
-- DROP FUNCTION IF EXISTS public.alpha_spark_outbox_events_immutable();
-- DROP TABLE IF EXISTS public.alpha_spark_outbox_events;
-- DROP TABLE IF EXISTS public.alpha_spark_outbox;
-- COMMIT;
