-- Migration: 20260612_111500_keyturner_sweep_report_rotation_reconcile
-- Purpose:   Add the shared Sweep TLS report HMAC secret to Keyturner's
--            rotation ledger without reading or storing the secret value.

WITH _rls AS (
    SELECT set_config('rls.role', 'platform_admin', true)
),
inventory(secret_name, rotation_days, nodes_updated, services_restarted, notes) AS (
    VALUES
        ('ALPHA_SWEEP_REPORT_SECRET', 90,
         ARRAY['brain','endpoint','gateway','sandbox']::text[],
         ARRAY[
             'com.jarvis.alpha.brain@brain',
             'com.jarvis.alpha.sweep-cert-renewal.brain@brain',
             'com.jarvis.alpha.sweep-cert-renewal.endpoint@endpoint',
             'com.jarvis.alpha.sweep-cert-renewal.gateway@gateway',
             'com.jarvis.alpha.sweep-cert-renewal.sandbox@sandbox'
         ]::text[],
         'Keyturner reconcile: Sweep report HMAC secret is tracked; not rotated by this migration.')
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
            ('ALPHA_SWEEP_REPORT_SECRET')
    ) AS expected(secret_name)
    WHERE NOT EXISTS (
        SELECT 1
        FROM public.v_secret_rotation_status s
        WHERE s.secret_name = expected.secret_name
    );

    IF v_missing <> 0 THEN
        RAISE EXCEPTION 'POST-FLIGHT Keyturner Sweep report secret reconcile FAILED: % missing', v_missing;
    END IF;

    RAISE NOTICE 'POST-FLIGHT Keyturner Sweep report secret reconcile OK';
END $$;
