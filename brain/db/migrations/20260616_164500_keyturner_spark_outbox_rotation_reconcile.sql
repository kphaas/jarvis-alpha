-- Migration: 20260616_164500_keyturner_spark_outbox_rotation_reconcile
-- Purpose:   Add Spark outbox encryption secrets to Keyturner's rotation
--            ledger without reading or storing the secret values.

WITH _rls AS (
    SELECT set_config('rls.role', 'platform_admin', true)
),
inventory(secret_name, rotation_days, nodes_updated, services_restarted, notes) AS (
    VALUES
        ('SPARK_OUTBOX_DIGEST_KEY', 90, ARRAY['brain']::text[],
         ARRAY['com.jarvis.alpha.brain@brain']::text[],
         'Keyturner reconcile: Spark outbox digest HMAC secret is tracked; not rotated by this migration.'),
        ('SPARK_OUTBOX_DIGEST_KEY_VERSION', 90, ARRAY['brain']::text[],
         ARRAY['com.jarvis.alpha.brain@brain']::text[],
         'Keyturner reconcile: Spark outbox digest key version is tracked; not rotated by this migration.'),
        ('SPARK_OUTBOX_PAYLOAD_KEY', 90, ARRAY['brain']::text[],
         ARRAY['com.jarvis.alpha.brain@brain']::text[],
         'Keyturner reconcile: Spark outbox payload encryption secret is tracked; not rotated by this migration.'),
        ('SPARK_OUTBOX_PAYLOAD_KEY_VERSION', 90, ARRAY['brain']::text[],
         ARRAY['com.jarvis.alpha.brain@brain']::text[],
         'Keyturner reconcile: Spark outbox payload key version is tracked; not rotated by this migration.')
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
            ('SPARK_OUTBOX_DIGEST_KEY'),
            ('SPARK_OUTBOX_DIGEST_KEY_VERSION'),
            ('SPARK_OUTBOX_PAYLOAD_KEY'),
            ('SPARK_OUTBOX_PAYLOAD_KEY_VERSION')
    ) AS expected(secret_name)
    WHERE NOT EXISTS (
        SELECT 1
        FROM public.v_secret_rotation_status s
        WHERE s.secret_name = expected.secret_name
    );

    IF v_missing <> 0 THEN
        RAISE EXCEPTION 'POST-FLIGHT Keyturner Spark outbox secret reconcile FAILED: % missing', v_missing;
    END IF;

    RAISE NOTICE 'POST-FLIGHT Keyturner Spark outbox secret reconcile OK';
END $$;
