-- Migration: 20260602_144500_keyturner_secret_classes
-- Purpose:   Keep Keyturner's registry metadata aligned with the expanded
--            managed-secret inventory.

UPDATE public.alpha_skill_registry
SET metadata = metadata
    || jsonb_build_object(
        'handled_secret_classes',
        jsonb_build_array(
            'api_key',
            'service_token',
            'service_jwt',
            'admin_pin',
            'db_password',
            'oauth_refresh_token',
            'oauth_client_secret',
            'cloudflare_api_token',
            'cloudflare_tunnel_token',
            'mattermost_token',
            'webhook_url',
            'pushover_token'
        )
    ),
    updated_at = NOW()
WHERE skill_name = 'secrets.rotate';

UPDATE public.alpha_agents
SET metadata = metadata
    || jsonb_build_object(
        'managed_inventory_version', 2,
        'managed_inventory', 'scripts/secrets_rotation.json'
    ),
    updated_at = NOW()
WHERE agent_id = 'keyturner';

DO $$
DECLARE
    v_has_oauth boolean;
    v_has_tunnel boolean;
BEGIN
    SELECT metadata->'handled_secret_classes' ? 'oauth_refresh_token',
           metadata->'handled_secret_classes' ? 'cloudflare_tunnel_token'
    INTO v_has_oauth, v_has_tunnel
    FROM public.alpha_skill_registry
    WHERE skill_name = 'secrets.rotate';

    IF COALESCE(v_has_oauth, false) IS NOT TRUE
       OR COALESCE(v_has_tunnel, false) IS NOT TRUE THEN
        RAISE EXCEPTION 'POST-FLIGHT Keyturner secret classes FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Keyturner secret classes OK';
END $$;
