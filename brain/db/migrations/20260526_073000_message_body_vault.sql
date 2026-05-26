-- Migration: 20260526_073000_message_body_vault
-- Purpose:   Privacy foundation for future Gmail/iMessage agents. Bodies are
--            stored encrypted with pgcrypto, FORCE-RLS protected, and have no
--            decrypt/read function in this phase.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.alpha_message_body_vault (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel                 TEXT NOT NULL,
    external_account        TEXT NOT NULL DEFAULT 'default',
    external_message_id     TEXT NOT NULL,
    external_thread_id      TEXT,
    body_ciphertext         BYTEA NOT NULL,
    body_hash               TEXT NOT NULL,
    body_size_bytes         INTEGER NOT NULL,
    summary                 TEXT,
    scope_required          TEXT NOT NULL,
    body_redaction_version  TEXT NOT NULL DEFAULT 'v1',
    retention_expires_at    TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT alpha_message_body_vault_channel_check
        CHECK (channel IN ('gmail', 'imessage')),
    CONSTRAINT alpha_message_body_vault_scope_check
        CHECK (
            (channel = 'gmail' AND scope_required = 'email.body.read')
            OR (channel = 'imessage' AND scope_required = 'imessage.body.read')
        ),
    CONSTRAINT alpha_message_body_vault_hash_check
        CHECK (body_hash ~ '^sha256:[a-f0-9]{64}$'),
    CONSTRAINT alpha_message_body_vault_body_size_check
        CHECK (body_size_bytes >= 0),
    CONSTRAINT alpha_message_body_vault_retention_check
        CHECK (retention_expires_at > created_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_message_body_vault_external
    ON public.alpha_message_body_vault(channel, external_account, external_message_id);

CREATE INDEX IF NOT EXISTS idx_message_body_vault_retention
    ON public.alpha_message_body_vault(retention_expires_at);

ALTER TABLE public.alpha_message_body_vault ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alpha_message_body_vault FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS message_body_vault_platform_admin_read
    ON public.alpha_message_body_vault;
CREATE POLICY message_body_vault_platform_admin_read
    ON public.alpha_message_body_vault
    FOR SELECT
    USING (current_setting('rls.role', true) = 'platform_admin');

DROP POLICY IF EXISTS message_body_vault_platform_admin_write
    ON public.alpha_message_body_vault;
CREATE POLICY message_body_vault_platform_admin_write
    ON public.alpha_message_body_vault
    FOR ALL
    USING (current_setting('rls.role', true) = 'platform_admin')
    WITH CHECK (current_setting('rls.role', true) = 'platform_admin');

CREATE OR REPLACE FUNCTION public.store_message_body_vault(
    p_channel TEXT,
    p_external_account TEXT,
    p_external_message_id TEXT,
    p_external_thread_id TEXT,
    p_body_plaintext TEXT,
    p_summary TEXT,
    p_body_key TEXT,
    p_retention_expires_at TIMESTAMPTZ
)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_id UUID;
    v_scope TEXT;
    v_body TEXT := COALESCE(p_body_plaintext, '');
BEGIN
    PERFORM set_config('rls.role', 'platform_admin', true);

    IF p_channel = 'gmail' THEN
        v_scope := 'email.body.read';
    ELSIF p_channel = 'imessage' THEN
        v_scope := 'imessage.body.read';
    ELSE
        RAISE EXCEPTION 'invalid message body channel: %', p_channel;
    END IF;

    IF COALESCE(p_external_message_id, '') = '' THEN
        RAISE EXCEPTION 'external_message_id is required';
    END IF;
    IF COALESCE(p_body_key, '') = '' THEN
        RAISE EXCEPTION 'body encryption key is required';
    END IF;
    IF p_retention_expires_at IS NULL OR p_retention_expires_at <= NOW() THEN
        RAISE EXCEPTION 'retention_expires_at must be in the future';
    END IF;

    INSERT INTO public.alpha_message_body_vault (
        channel,
        external_account,
        external_message_id,
        external_thread_id,
        body_ciphertext,
        body_hash,
        body_size_bytes,
        summary,
        scope_required,
        retention_expires_at
    )
    VALUES (
        p_channel,
        COALESCE(NULLIF(p_external_account, ''), 'default'),
        p_external_message_id,
        p_external_thread_id,
        pgp_sym_encrypt(v_body, p_body_key, 'compress-algo=1, cipher-algo=aes256'),
        'sha256:' || encode(digest(v_body, 'sha256'), 'hex'),
        octet_length(convert_to(v_body, 'UTF8')),
        p_summary,
        v_scope,
        p_retention_expires_at
    )
    ON CONFLICT (channel, external_account, external_message_id)
    DO UPDATE SET
        external_thread_id = EXCLUDED.external_thread_id,
        body_ciphertext = EXCLUDED.body_ciphertext,
        body_hash = EXCLUDED.body_hash,
        body_size_bytes = EXCLUDED.body_size_bytes,
        summary = EXCLUDED.summary,
        scope_required = EXCLUDED.scope_required,
        retention_expires_at = EXCLUDED.retention_expires_at,
        updated_at = NOW()
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.alpha_message_body_vault
    TO jarvis_alpha_app, jarvis_alpha_writer;

GRANT EXECUTE ON FUNCTION public.store_message_body_vault(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ
) TO jarvis_alpha_app, jarvis_alpha_writer;

COMMENT ON TABLE public.alpha_message_body_vault IS
    'Encrypted 30-day body vault for future Gmail/iMessage agents. No decrypt/read function in Wave 0.';

DO $$
DECLARE
    v_id UUID;
    v_plain TEXT;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_extension
        WHERE extname = 'pgcrypto'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT pgcrypto extension missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_class
        WHERE relname = 'alpha_message_body_vault'
          AND relnamespace = 'public'::regnamespace
          AND relrowsecurity
          AND relforcerowsecurity
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT alpha_message_body_vault FORCE RLS FAILED';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_proc
        WHERE proname = 'store_message_body_vault'
          AND pronamespace = 'public'::regnamespace
          AND pg_get_functiondef(oid) LIKE '%set_config(''rls.role'', ''platform_admin'', true)%'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT store_message_body_vault SECDEF FAILED';
    END IF;

    v_id := public.store_message_body_vault(
        'gmail',
        'postflight',
        'postflight-message',
        'postflight-thread',
        'postflight secret body',
        'postflight summary',
        'postflight-key',
        NOW() + INTERVAL '1 hour'
    );

    SELECT pgp_sym_decrypt(body_ciphertext, 'postflight-key')
    INTO v_plain
    FROM public.alpha_message_body_vault
    WHERE id = v_id;

    IF v_plain <> 'postflight secret body' THEN
        RAISE EXCEPTION 'POST-FLIGHT message body encryption roundtrip FAILED';
    END IF;

    DELETE FROM public.alpha_message_body_vault
    WHERE id = v_id;

    IF EXISTS (
        SELECT 1
        FROM pg_proc
        WHERE pronamespace = 'public'::regnamespace
          AND proname IN (
              'get_message_body_vault',
              'decrypt_message_body_vault',
              'read_message_body_vault'
          )
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT message body decrypt function should not exist in Wave 0';
    END IF;

    RAISE NOTICE 'POST-FLIGHT message body vault privacy rail OK';
END $$;
