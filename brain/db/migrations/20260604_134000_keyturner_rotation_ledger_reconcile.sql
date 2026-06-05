-- Migration: 20260604_134000_keyturner_rotation_ledger_reconcile
-- Purpose:   Reconcile Keyturner's configured secret inventory into the
--            alpha_secret_rotations ledger without reading or storing secret
--            values. This repairs drift where prior inventory migrations were
--            skipped but the live ledger is empty.

WITH _rls AS (
    SELECT set_config('rls.role', 'platform_admin', true)
),
inventory(secret_name, rotation_days, nodes_updated, services_restarted, notes) AS (
    VALUES
        ('ANTHROPIC_API_KEY', 90, ARRAY['gateway']::text[], ARRAY['com.jarvis.alpha.gateway@gateway']::text[],
         'Keyturner reconcile: Gateway provider key is tracked; not rotated by this migration.'),
        ('GEMINI_API_KEY', 90, ARRAY['gateway']::text[], ARRAY['com.jarvis.alpha.gateway@gateway']::text[],
         'Keyturner reconcile: Gateway provider key is tracked; not rotated by this migration.'),
        ('PERPLEXITY_API_KEY', 90, ARRAY['gateway']::text[], ARRAY['com.jarvis.alpha.gateway@gateway']::text[],
         'Keyturner reconcile: Gateway provider key is tracked; not rotated by this migration.'),
        ('GITHUB_TOKEN', 90, ARRAY['brain','gateway','endpoint','sandbox']::text[], ARRAY['com.jarvis.alpha.brain@brain','com.jarvis.forge.dashboard@sandbox']::text[],
         'Keyturner reconcile: GitHub token is tracked; not rotated by this migration.'),
        ('ALPHA_PIN', 90, ARRAY['brain']::text[], ARRAY['com.jarvis.alpha.brain@brain']::text[],
         'Keyturner reconcile: Alpha admin PIN is tracked; not rotated by this migration.'),
        ('JARVIS_FAMILY_SMOKE_PIN', 90, ARRAY['brain']::text[], ARRAY['com.jarvis.family.api@brain']::text[],
         'Keyturner reconcile: Family synthetic parent smoke PIN is tracked; not rotated by this migration.'),
        ('JARVIS_FAMILY_EXTERNAL_SMOKE_PIN', 90, ARRAY['brain']::text[], ARRAY['com.jarvis.family.api@brain']::text[],
         'Keyturner reconcile: Family synthetic external smoke PIN is tracked; not rotated by this migration.'),
        ('ALPHA_BUDDY_TOKEN', 7, ARRAY['brain']::text[], ARRAY['com.jarvis.alpha.buddy@brain']::text[],
         'Keyturner reconcile: Buddy service JWT is owned by token rotator; not rotated by this migration.'),
        ('ALPHA_BRAIN_SERVICE_TOKEN', 7, ARRAY['brain']::text[], ARRAY['com.jarvis.alpha.brain@brain']::text[],
         'Keyturner reconcile: Brain service JWT is owned by token rotator; not rotated by this migration.'),
        ('ALPHA_SERVICE_TOKEN_GATEWAY', 7, ARRAY['gateway']::text[], ARRAY['com.jarvis.alpha.gateway@gateway']::text[],
         'Keyturner reconcile: Gateway ALPHA_SERVICE_TOKEN is owned by token rotator; not rotated by this migration.'),
        ('ALPHA_SERVICE_TOKEN_ENDPOINT', 7, ARRAY['endpoint']::text[], ARRAY['com.jarvis.alpha.endpoint@endpoint']::text[],
         'Keyturner reconcile: Endpoint ALPHA_SERVICE_TOKEN is owned by token rotator; not rotated by this migration.'),
        ('ALPHA_SERVICE_TOKEN_SANDBOX', 7, ARRAY['sandbox']::text[], ARRAY['com.jarvis.forge.dashboard@sandbox']::text[],
         'Keyturner reconcile: Sandbox ALPHA_SERVICE_TOKEN is owned by token rotator; not rotated by this migration.'),
        ('GATEWAY_TOKEN', 90, ARRAY['brain','sandbox']::text[], ARRAY['com.jarvis.alpha.brain@brain']::text[],
         'Keyturner reconcile: shared Gateway API token is tracked; not rotated by this migration.'),
        ('ALPHA_GMAIL_REFRESH_TOKEN', 7, ARRAY['brain']::text[], ARRAY['com.jarvis.alpha.gmail-health@brain','com.jarvis.alpha.brain@brain']::text[],
         'Keyturner reconcile: Gmail OAuth refresh token is tracked; interactive Google consent may be required for actual rotation.'),
        ('ALPHA_GMAIL_CLIENT_SECRET', 180, ARRAY['brain']::text[], ARRAY['com.jarvis.alpha.gmail-health@brain','com.jarvis.alpha.brain@brain']::text[],
         'Keyturner reconcile: Gmail OAuth client secret is tracked; not rotated by this migration.'),
        ('CLOUDFLARE_API_TOKEN', 90, ARRAY['brain']::text[], ARRAY['com.jarvis.alpha.brain@brain']::text[],
         'Keyturner reconcile: Cloudflare API token is tracked; not rotated by this migration.'),
        ('CLOUDFLARE_TUNNEL_TOKEN', 180, ARRAY['endpoint']::text[], ARRAY['com.cloudflare.cloudflared@endpoint']::text[],
         'Keyturner reconcile: Cloudflare tunnel token is tracked; not rotated by this migration.'),
        ('MATTERMOST_BOT_TOKEN', 180, ARRAY['gateway']::text[], ARRAY['com.jarvis.alpha.gateway@gateway']::text[],
         'Keyturner reconcile: Mattermost bot token is tracked; not rotated by this migration.'),
        ('MATTERMOST_WEBHOOK_URL_SECURITY_ALERTS', 180, ARRAY['gateway']::text[], ARRAY['com.jarvis.alpha.gateway@gateway']::text[],
         'Keyturner reconcile: Mattermost security webhook is tracked; not rotated by this migration.'),
        ('PUSHOVER_APP_TOKEN', 180, ARRAY['gateway']::text[], ARRAY['com.jarvis.alpha.gateway@gateway']::text[],
         'Keyturner reconcile: Pushover app token is tracked; not rotated by this migration.'),
        ('POSTGRES_PASSWORD', 180, ARRAY['brain']::text[], ARRAY['com.jarvis.alpha.brain@brain','com.jarvis.alpha.buddy@brain','com.jarvis.alpha.executor@brain','com.jarvis.family.api@brain']::text[],
         'Keyturner reconcile: manual Postgres jarvisbrain password is tracked; not rotated by this migration.'),
        ('TEMPORAL_DB_PASSWORD', 180, ARRAY['brain']::text[], ARRAY['com.jarvis.alpha.temporal.server@brain']::text[],
         'Keyturner reconcile: manual Temporal DB password is tracked; not rotated by this migration.')
)
INSERT INTO public.alpha_secret_rotations
    (secret_name, rotated_by, rotation_days, nodes_updated, services_restarted,
     verify_status, value_hash, notes)
SELECT i.secret_name,
       'keyturner@reconcile',
       i.rotation_days,
       i.nodes_updated,
       i.services_restarted,
       'skipped',
       NULL,
       i.notes
FROM inventory i, _rls
WHERE NOT EXISTS (
    SELECT 1
    FROM public.alpha_secret_rotations r
    WHERE r.secret_name = i.secret_name
);

DO $$
DECLARE
    v_missing integer;
BEGIN
    SELECT COUNT(*)
    INTO v_missing
    FROM (
        VALUES
            ('ANTHROPIC_API_KEY'), ('GEMINI_API_KEY'), ('PERPLEXITY_API_KEY'),
            ('GITHUB_TOKEN'), ('ALPHA_PIN'), ('JARVIS_FAMILY_SMOKE_PIN'),
            ('JARVIS_FAMILY_EXTERNAL_SMOKE_PIN'), ('ALPHA_BUDDY_TOKEN'),
            ('ALPHA_BRAIN_SERVICE_TOKEN'), ('ALPHA_SERVICE_TOKEN_GATEWAY'),
            ('ALPHA_SERVICE_TOKEN_ENDPOINT'), ('ALPHA_SERVICE_TOKEN_SANDBOX'),
            ('GATEWAY_TOKEN'), ('ALPHA_GMAIL_REFRESH_TOKEN'),
            ('ALPHA_GMAIL_CLIENT_SECRET'), ('CLOUDFLARE_API_TOKEN'),
            ('CLOUDFLARE_TUNNEL_TOKEN'), ('MATTERMOST_BOT_TOKEN'),
            ('MATTERMOST_WEBHOOK_URL_SECURITY_ALERTS'), ('PUSHOVER_APP_TOKEN'),
            ('POSTGRES_PASSWORD'), ('TEMPORAL_DB_PASSWORD')
    ) AS expected(secret_name)
    WHERE NOT EXISTS (
        SELECT 1
        FROM public.v_secret_rotation_status s
        WHERE s.secret_name = expected.secret_name
    );

    IF v_missing <> 0 THEN
        RAISE EXCEPTION 'POST-FLIGHT Keyturner rotation ledger reconcile FAILED: % missing', v_missing;
    END IF;

    RAISE NOTICE 'POST-FLIGHT Keyturner rotation ledger reconcile OK';
END $$;
