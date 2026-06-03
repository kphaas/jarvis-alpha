-- Migration: 20260603_083000_keyturner_family_external_smoke_pin
-- Purpose:   Onboard the Family external smoke PIN into Keyturner's rotation
--            ledger without changing the live value.

WITH _rls AS (
    SELECT set_config('rls.role', 'platform_admin', true)
)
INSERT INTO public.alpha_secret_rotations
    (secret_name, rotated_by, rotation_days, nodes_updated, services_restarted,
     verify_status, value_hash, notes)
SELECT 'JARVIS_FAMILY_EXTERNAL_SMOKE_PIN',
       'keyturner@inventory',
       90,
       ARRAY['brain']::text[],
       ARRAY['com.jarvis.family.api@brain']::text[],
       'skipped',
       NULL,
       'Keyturner inventory onboarding: Family synthetic external shared-portal smoke PIN is now tracked; not rotated by this migration.'
FROM _rls
WHERE NOT EXISTS (
    SELECT 1
    FROM public.alpha_secret_rotations r
    WHERE r.secret_name = 'JARVIS_FAMILY_EXTERNAL_SMOKE_PIN'
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.v_secret_rotation_status s
        WHERE s.secret_name = 'JARVIS_FAMILY_EXTERNAL_SMOKE_PIN'
    ) THEN
        RAISE EXCEPTION 'POST-FLIGHT Keyturner Family external smoke PIN inventory FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Keyturner Family external smoke PIN inventory OK';
END $$;
