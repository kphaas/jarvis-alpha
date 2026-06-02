-- Migration: 20260602_101500_keyturner_db_password_baseline
-- Purpose:   Bring manual DB-password secrets under the Keyturner rotation
--            ledger without changing live passwords in this migration.

WITH _rls AS (
    SELECT set_config('rls.role', 'platform_admin', true)
),
baseline(secret_name, rotation_days, nodes_updated, services_restarted, notes) AS (
    VALUES
        (
            'POSTGRES_PASSWORD',
            180,
            ARRAY['brain']::text[],
            ARRAY[
                'com.jarvis.alpha.brain@brain',
                'com.jarvis.alpha.buddy@brain',
                'com.jarvis.alpha.executor@brain',
                'com.jarvis.family.api@brain'
            ]::text[],
            'Keyturner baseline: existing DB password verified as tracked; not rotated by this migration.'
        ),
        (
            'TEMPORAL_DB_PASSWORD',
            180,
            ARRAY['brain']::text[],
            ARRAY['com.jarvis.alpha.temporal.server@brain']::text[],
            'Keyturner baseline: existing Temporal DB password verified as tracked; not rotated by this migration.'
        )
)
INSERT INTO public.alpha_secret_rotations
    (secret_name, rotated_by, rotation_days, nodes_updated, services_restarted,
     verify_status, value_hash, notes)
SELECT b.secret_name,
       'keyturner@baseline',
       b.rotation_days,
       b.nodes_updated,
       b.services_restarted,
       'passed',
       NULL,
       b.notes
FROM baseline b, _rls
WHERE NOT EXISTS (
    SELECT 1
    FROM public.alpha_secret_rotations r
    WHERE r.secret_name = b.secret_name
);

DO $$
DECLARE
    v_missing integer;
BEGIN
    SELECT COUNT(*)
    INTO v_missing
    FROM (VALUES ('POSTGRES_PASSWORD'), ('TEMPORAL_DB_PASSWORD')) AS expected(secret_name)
    WHERE NOT EXISTS (
        SELECT 1
        FROM public.v_secret_rotation_status s
        WHERE s.secret_name = expected.secret_name
          AND s.last_verify_status = 'passed'
    );

    IF v_missing <> 0 THEN
        RAISE EXCEPTION 'POST-FLIGHT Keyturner DB password baseline FAILED';
    END IF;

    RAISE NOTICE 'POST-FLIGHT Keyturner DB password baseline OK';
END $$;
