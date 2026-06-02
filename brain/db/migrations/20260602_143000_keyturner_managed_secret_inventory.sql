-- Migration: 20260602_143000_keyturner_managed_secret_inventory
-- Purpose:   Onboard every Keyturner-managed secret into the rotation ledger
--            without changing live values. Future rotations append real rows.

WITH _rls AS (
    SELECT set_config('rls.role', 'platform_admin', true)
),
inventory(secret_name, rotation_days, nodes_updated, services_restarted, notes) AS (
    VALUES
        ('ANTHROPIC_API_KEY', 90, ARRAY['gateway']::text[], ARRAY['com.jarvis.alpha.gateway@gateway']::text[],
         'Keyturner inventory onboarding: Gateway provider key is now tracked; not rotated by this migration.'),
        ('GEMINI_API_KEY', 90, ARRAY['gateway']::text[], ARRAY['com.jarvis.alpha.gateway@gateway']::text[],
         'Keyturner inventory onboarding: Gateway provider key is now tracked; not rotated by this migration.'),
        ('PERPLEXITY_API_KEY', 90, ARRAY['gateway']::text[], ARRAY['com.jarvis.alpha.gateway@gateway']::text[],
         'Keyturner inventory onboarding: Gateway provider key is now tracked; not rotated by this migration.'),
        ('GATEWAY_TOKEN', 90, ARRAY['brain','sandbox']::text[], ARRAY['com.jarvis.alpha.brain@brain']::text[],
         'Keyturner inventory onboarding: Gateway API token is now tracked; not rotated by this migration.'),
        ('JARVIS_FAMILY_SMOKE_PIN', 90, ARRAY['brain']::text[], ARRAY['com.jarvis.family.api@brain']::text[],
         'Keyturner inventory onboarding: Family smoke PIN is now tracked; not rotated by this migration.'),
        ('ALPHA_BUDDY_TOKEN', 7, ARRAY['brain']::text[], ARRAY['com.jarvis.alpha.buddy@brain']::text[],
         'Keyturner inventory onboarding: Buddy service JWT is owned by token rotator; not rotated by this migration.'),
        ('ALPHA_BRAIN_SERVICE_TOKEN', 7, ARRAY['brain']::text[], ARRAY['com.jarvis.alpha.brain@brain']::text[],
         'Keyturner inventory onboarding: Brain service JWT is owned by token rotator; not rotated by this migration.'),
        ('ALPHA_SERVICE_TOKEN_GATEWAY', 7, ARRAY['gateway']::text[], ARRAY['com.jarvis.alpha.gateway@gateway']::text[],
         'Keyturner inventory onboarding: Gateway ALPHA_SERVICE_TOKEN is owned by token rotator; not rotated by this migration.'),
        ('ALPHA_SERVICE_TOKEN_ENDPOINT', 7, ARRAY['endpoint']::text[], ARRAY['com.jarvis.alpha.endpoint@endpoint']::text[],
         'Keyturner inventory onboarding: Endpoint ALPHA_SERVICE_TOKEN is owned by token rotator; not rotated by this migration.'),
        ('ALPHA_SERVICE_TOKEN_SANDBOX', 7, ARRAY['sandbox']::text[], ARRAY['com.jarvis.forge.dashboard@sandbox']::text[],
         'Keyturner inventory onboarding: Sandbox ALPHA_SERVICE_TOKEN is owned by token rotator; not rotated by this migration.'),
        ('ALPHA_GMAIL_REFRESH_TOKEN', 7, ARRAY['brain']::text[], ARRAY['com.jarvis.alpha.gmail-health@brain','com.jarvis.alpha.brain@brain']::text[],
         'Keyturner inventory onboarding: Gmail OAuth refresh token is tracked; interactive Google consent may be required for actual rotation.'),
        ('ALPHA_GMAIL_CLIENT_SECRET', 180, ARRAY['brain']::text[], ARRAY['com.jarvis.alpha.gmail-health@brain','com.jarvis.alpha.brain@brain']::text[],
         'Keyturner inventory onboarding: Gmail OAuth client secret is tracked; not rotated by this migration.'),
        ('CLOUDFLARE_API_TOKEN', 90, ARRAY['brain']::text[], ARRAY['com.jarvis.alpha.brain@brain']::text[],
         'Keyturner inventory onboarding: Cloudflare API token is tracked; not rotated by this migration.'),
        ('CLOUDFLARE_TUNNEL_TOKEN', 180, ARRAY['endpoint']::text[], ARRAY['com.cloudflare.cloudflared@endpoint']::text[],
         'Keyturner inventory onboarding: Cloudflare tunnel token is tracked; not rotated by this migration.'),
        ('MATTERMOST_BOT_TOKEN', 180, ARRAY['gateway']::text[], ARRAY['com.jarvis.alpha.gateway@gateway']::text[],
         'Keyturner inventory onboarding: Mattermost bot token is tracked; not rotated by this migration.'),
        ('MATTERMOST_WEBHOOK_URL_SECURITY_ALERTS', 180, ARRAY['gateway']::text[], ARRAY['com.jarvis.alpha.gateway@gateway']::text[],
         'Keyturner inventory onboarding: Mattermost security webhook is tracked; not rotated by this migration.'),
        ('PUSHOVER_APP_TOKEN', 180, ARRAY['gateway']::text[], ARRAY['com.jarvis.alpha.gateway@gateway']::text[],
         'Keyturner inventory onboarding: Pushover app token is tracked; not rotated by this migration.')
)
INSERT INTO public.alpha_secret_rotations
    (secret_name, rotated_by, rotation_days, nodes_updated, services_restarted,
     verify_status, value_hash, notes)
SELECT i.secret_name,
       'keyturner@inventory',
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
            ('GATEWAY_TOKEN'), ('JARVIS_FAMILY_SMOKE_PIN'),
            ('ALPHA_BUDDY_TOKEN'), ('ALPHA_BRAIN_SERVICE_TOKEN'),
            ('ALPHA_SERVICE_TOKEN_GATEWAY'), ('ALPHA_SERVICE_TOKEN_ENDPOINT'),
            ('ALPHA_SERVICE_TOKEN_SANDBOX'), ('ALPHA_GMAIL_REFRESH_TOKEN'),
            ('ALPHA_GMAIL_CLIENT_SECRET'), ('CLOUDFLARE_API_TOKEN'),
            ('CLOUDFLARE_TUNNEL_TOKEN'), ('MATTERMOST_BOT_TOKEN'),
            ('MATTERMOST_WEBHOOK_URL_SECURITY_ALERTS'), ('PUSHOVER_APP_TOKEN')
    ) AS expected(secret_name)
    WHERE NOT EXISTS (
        SELECT 1
        FROM public.v_secret_rotation_status s
        WHERE s.secret_name = expected.secret_name
    );

    IF v_missing <> 0 THEN
        RAISE EXCEPTION 'POST-FLIGHT Keyturner managed inventory FAILED: % missing', v_missing;
    END IF;

    RAISE NOTICE 'POST-FLIGHT Keyturner managed inventory OK';
END $$;
