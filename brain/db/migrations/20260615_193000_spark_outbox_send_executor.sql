-- Purpose: SECDEF helpers for approved Spark outbox send execution.
-- This adds metadata/ciphertext retrieval for the app-side sender and status
-- transition auditing. It does not add SQL plaintext decrypt.

BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
SELECT pg_advisory_xact_lock(20260615193000);

CREATE OR REPLACE FUNCTION public.get_spark_outbox_item_for_send(
    p_outbox_id uuid
)
RETURNS TABLE (
    outbox_id uuid,
    channel text,
    principal_id text,
    target_ref_hash text,
    target_label text,
    approval_queue_id uuid,
    approval_parameters_hash text,
    approval_status text,
    approval_expires_at timestamptz,
    approval_row_parameters_hash text,
    draft_text_ciphertext bytea,
    draft_text_hash text,
    payload_key_version text,
    status text,
    send_attempt_count integer
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $$
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    RETURN QUERY
    SELECT
        o.id,
        o.channel,
        o.principal_id,
        o.target_ref_hash,
        o.target_label,
        o.approval_queue_id,
        o.approval_parameters_hash,
        q.status,
        q.expires_at,
        q.parameters_hash,
        o.draft_text_ciphertext,
        o.draft_text_hash,
        o.payload_key_version,
        o.status,
        o.send_attempt_count
    FROM public.alpha_spark_outbox AS o
    JOIN public.alpha_approval_queue AS q
      ON q.id = o.approval_queue_id
    WHERE o.id = p_outbox_id
    LIMIT 1;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_spark_outbox_event(
    p_outbox_id uuid,
    p_event_type text,
    p_actor_sub text,
    p_actor_type text,
    p_event_metadata jsonb DEFAULT '{}'::jsonb,
    p_error_class text DEFAULT NULL,
    p_error_message text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'pg_catalog', 'public'
AS $$
DECLARE
    v_event_type text := lower(btrim(p_event_type));
    v_actor_sub text := btrim(p_actor_sub);
    v_actor_type text := btrim(p_actor_type);
    v_event_payload jsonb := COALESCE(p_event_metadata, '{}'::jsonb);
    v_status text;
    v_updated integer := 0;
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);
    SET LOCAL lock_timeout = '2s';
    SET LOCAL statement_timeout = '10s';

    IF v_event_type NOT IN (
        'created', 'approval_synced', 'send_ready',
        'sending', 'sent', 'send_failed', 'cancelled'
    ) THEN
        RETURN jsonb_build_object('recorded', false, 'reason', 'invalid_event_type');
    END IF;
    IF char_length(v_actor_sub) < 1 OR char_length(v_actor_sub) > 160 THEN
        RETURN jsonb_build_object('recorded', false, 'reason', 'invalid_actor_sub');
    END IF;
    IF char_length(v_actor_type) < 1 OR char_length(v_actor_type) > 80 THEN
        RETURN jsonb_build_object('recorded', false, 'reason', 'invalid_actor_type');
    END IF;
    IF jsonb_typeof(v_event_payload) <> 'object' THEN
        RETURN jsonb_build_object('recorded', false, 'reason', 'invalid_event_metadata');
    END IF;

    IF v_event_type = 'sending' THEN
        UPDATE public.alpha_spark_outbox
        SET
            status = 'sending',
            send_attempt_count = send_attempt_count + 1,
            updated_at = NOW()
        WHERE id = p_outbox_id
          AND status IN ('pending_approval', 'approved', 'send_ready', 'send_failed')
        RETURNING status INTO v_status;
    ELSIF v_event_type = 'sent' THEN
        UPDATE public.alpha_spark_outbox
        SET
            status = 'sent',
            sent_at = COALESCE(sent_at, NOW()),
            updated_at = NOW(),
            last_error_class = NULL,
            last_error_message = NULL
        WHERE id = p_outbox_id
          AND status = 'sending'
        RETURNING status INTO v_status;
    ELSIF v_event_type = 'send_failed' THEN
        UPDATE public.alpha_spark_outbox
        SET
            status = 'send_failed',
            updated_at = NOW(),
            last_error_class = NULLIF(btrim(COALESCE(p_error_class, '')), ''),
            last_error_message = NULLIF(btrim(COALESCE(p_error_message, '')), '')
        WHERE id = p_outbox_id
          AND status = 'sending'
        RETURNING status INTO v_status;
    ELSIF v_event_type = 'cancelled' THEN
        UPDATE public.alpha_spark_outbox
        SET
            status = 'cancelled',
            updated_at = NOW()
        WHERE id = p_outbox_id
          AND status NOT IN ('sent', 'cancelled')
        RETURNING status INTO v_status;
    ELSE
        SELECT status
        INTO v_status
        FROM public.alpha_spark_outbox
        WHERE id = p_outbox_id;
    END IF;

    GET DIAGNOSTICS v_updated = ROW_COUNT;

    IF v_status IS NULL THEN
        RETURN jsonb_build_object('recorded', false, 'reason', 'outbox_not_found');
    END IF;

    INSERT INTO public.alpha_spark_outbox_events (
        outbox_id,
        event_type,
        actor_sub,
        actor_type,
        event_payload
    )
    VALUES (
        p_outbox_id,
        v_event_type,
        v_actor_sub,
        v_actor_type,
        v_event_payload
    );

    RETURN jsonb_build_object(
        'recorded', true,
        'outbox_id', p_outbox_id,
        'event_type', v_event_type,
        'status', v_status,
        'updated', v_updated > 0
    );
END;
$$;

REVOKE ALL ON FUNCTION public.get_spark_outbox_item_for_send(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_spark_outbox_event(
    uuid, text, text, text, jsonb, text, text
) FROM PUBLIC;

DO $owner$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvisbrain') THEN
        EXECUTE
            'ALTER FUNCTION public.get_spark_outbox_item_for_send'
            || '(uuid) OWNER TO jarvisbrain';
        EXECUTE
            'ALTER FUNCTION public.record_spark_outbox_event'
            || '(uuid, text, text, text, jsonb, text, text) OWNER TO jarvisbrain';
    END IF;
END
$owner$;

DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_app') THEN
        GRANT EXECUTE ON FUNCTION public.get_spark_outbox_item_for_send(
            uuid
        ) TO jarvis_alpha_app;
        GRANT EXECUTE ON FUNCTION public.record_spark_outbox_event(
            uuid, text, text, text, jsonb, text, text
        ) TO jarvis_alpha_app;
    END IF;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_alpha_writer') THEN
        GRANT EXECUTE ON FUNCTION public.get_spark_outbox_item_for_send(
            uuid
        ) TO jarvis_alpha_writer;
        GRANT EXECUTE ON FUNCTION public.record_spark_outbox_event(
            uuid, text, text, text, jsonb, text, text
        ) TO jarvis_alpha_writer;
    END IF;
END
$grants$;

COMMENT ON FUNCTION public.get_spark_outbox_item_for_send(uuid) IS
    'Returns one Spark outbox ciphertext and approval metadata for app-side approved-send execution.';
COMMENT ON FUNCTION public.record_spark_outbox_event(
    uuid, text, text, text, jsonb, text, text
) IS
    'Appends Spark outbox send audit events and updates send status transitions. No plaintext draft text.';

DO $postcheck$
DECLARE
    v_missing integer;
    v_decrypt_helpers integer;
BEGIN
    SELECT count(*)::integer
    INTO v_missing
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public'
      AND p.proname IN (
          'get_spark_outbox_item_for_send',
          'record_spark_outbox_event'
      )
      AND NOT p.prosecdef;

    IF COALESCE(v_missing, 0) <> 0 THEN
        RAISE EXCEPTION 'Spark outbox send SECDEF postcheck failed';
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
-- DROP FUNCTION IF EXISTS public.record_spark_outbox_event(
--     uuid, text, text, text, jsonb, text, text
-- );
-- DROP FUNCTION IF EXISTS public.get_spark_outbox_item_for_send(uuid);
-- COMMIT;
