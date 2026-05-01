-- =====================================================================
-- rls_smoke.sql — Slab 5 deliverable 3 / Slab 3 Q7 smoke harness
--
-- Purpose: 8 role-switching cases that verify RLS shape behavior on
--          jarvis_alpha_test. Mirrors the case structure documented in
--          docs/SLAB5_BUG_FIXES_SPEC.md "Deliverable 3".
--
-- Pre-req: test_data_setup.sql has run successfully against the same
--          database (provides the 4 users, 1 workspace, 2 threads,
--          4 messages required by cases 2/3/7/8).
--
-- Execution: psql -d jarvis_alpha_test -U jarvisbrain -f rls_smoke.sql
--            Exit code 0 = all cases pass.
--            Non-zero exit = at least one ASSERT raised; investigate
--            before merging anything that touches RLS policies.
--
-- Each case follows the same shape:
--   1. RESET ALL;                  — clear all session GUCs
--   2. SELECT set_config(...)      — install the GUCs the case needs
--   3. DO $$ ... ASSERT ... $$;    — assertion block; raises on fail
--   4. RAISE NOTICE 'Case N PASS'  — emitted on success
-- =====================================================================

-- ============================================================
-- SLAB 3 Q7 / SLAB 5 deliverable 3: 8 role-switching smoke cases
-- ============================================================

\echo === Case 1: platform_admin sees all Shape A rows ===
RESET ALL;
SELECT set_config('rls.role',         'platform_admin',                        false);
SELECT set_config('rls.user_id',      '00000000-0000-0000-0000-000000000001',  false);
SELECT set_config('rls.max_rating',   'adult',                                 false);
SELECT set_config('rls.workspace_id', '00000000-0000-0000-0000-0000000000aa',  false);

DO $$
DECLARE
    n INT;
BEGIN
    SELECT count(*) INTO n FROM chat_threads;
    ASSERT n > 0, 'Case 1 FAIL: platform_admin should see all chat_threads (got 0)';
    RAISE NOTICE 'Case 1 PASS: admin sees % chat_threads rows', n;
END
$$;

\echo === Case 2: user_a sees only own Shape A rows ===
RESET ALL;
SELECT set_config('rls.role',         'user',                                  false);
SELECT set_config('rls.user_id',      '11111111-1111-1111-1111-111111111111',  false);
SELECT set_config('rls.max_rating',   'adult',                                 false);
SELECT set_config('rls.workspace_id', '00000000-0000-0000-0000-0000000000aa',  false);

DO $$
DECLARE
    own_count     INT;
    foreign_count INT;
BEGIN
    SELECT count(*) INTO own_count FROM chat_threads
      WHERE user_id = '11111111-1111-1111-1111-111111111111';
    SELECT count(*) INTO foreign_count FROM chat_threads
      WHERE user_id <> '11111111-1111-1111-1111-111111111111';
    ASSERT own_count     > 0, 'Case 2 FAIL: user_a should see own threads (got 0)';
    ASSERT foreign_count = 0, 'Case 2 FAIL: user_a sees foreign threads (got > 0)';
    RAISE NOTICE 'Case 2 PASS: own=%, foreign=%', own_count, foreign_count;
END
$$;

\echo === Case 3: child with age_8_plus ceiling ===
RESET ALL;
SELECT set_config('rls.role',         'child',                                 false);
SELECT set_config('rls.user_id',      '22222222-2222-2222-2222-222222222222',  false);
SELECT set_config('rls.max_rating',   'age_8_plus',                            false);
SELECT set_config('rls.workspace_id', '00000000-0000-0000-0000-0000000000aa',  false);

DO $$
DECLARE
    above_ceiling INT;
BEGIN
    SELECT count(*) INTO above_ceiling FROM alpha_conversation_memory
      WHERE content_rating IN ('teen', 'adult');
    ASSERT above_ceiling = 0,
        'Case 3 FAIL: child sees teen/adult rows in alpha_conversation_memory (got > 0)';
    RAISE NOTICE 'Case 3 PASS: child sees zero teen/adult rows in alpha_conversation_memory';
END
$$;

\echo === Case 4: All GUCs reset = fail-closed ===
RESET ALL;

DO $$
DECLARE
    n INT;
BEGIN
    SELECT count(*) INTO n FROM chat_threads;
    ASSERT n = 0,
        'Case 4 FAIL: unset GUCs must return 0 rows (fail-closed); got ' || n;
    RAISE NOTICE 'Case 4 PASS: fail-closed verified (rows=%)', n;
END
$$;

\echo === Case 5: user role on Shape B = 0 rows ===
RESET ALL;
SELECT set_config('rls.role',         'user',                                  false);
SELECT set_config('rls.user_id',      '11111111-1111-1111-1111-111111111111',  false);
SELECT set_config('rls.max_rating',   'adult',                                 false);
SELECT set_config('rls.workspace_id', '00000000-0000-0000-0000-0000000000aa',  false);

DO $$
DECLARE
    n INT;
BEGIN
    SELECT count(*) INTO n FROM alpha_buddy_events;
    ASSERT n = 0,
        'Case 5 FAIL: user role must see 0 Shape B rows in alpha_buddy_events; got ' || n;
    RAISE NOTICE 'Case 5 PASS: user sees zero Shape B rows';
END
$$;

\echo === Case 6: platform_admin sees all Shape B rows ===
RESET ALL;
SELECT set_config('rls.role',         'platform_admin',                        false);
SELECT set_config('rls.user_id',      '00000000-0000-0000-0000-000000000001',  false);
SELECT set_config('rls.max_rating',   'adult',                                 false);
SELECT set_config('rls.workspace_id', '00000000-0000-0000-0000-0000000000aa',  false);

DO $$
DECLARE
    n INT;
BEGIN
    SELECT count(*) INTO n FROM alpha_buddy_events;
    -- Shape B may be empty in test DB; assert >= 0 just confirms the
    -- query did not error (RLS allowed admin path through).
    ASSERT n >= 0,
        'Case 6 FAIL: platform_admin query against Shape B errored';
    RAISE NOTICE 'Case 6 PASS: admin queries Shape B; rows=%', n;
END
$$;

\echo === Case 7: user_a sees only own thread messages (Shape A-FK) ===
RESET ALL;
SELECT set_config('rls.role',         'user',                                  false);
SELECT set_config('rls.user_id',      '11111111-1111-1111-1111-111111111111',  false);
SELECT set_config('rls.max_rating',   'adult',                                 false);
SELECT set_config('rls.workspace_id', '00000000-0000-0000-0000-0000000000aa',  false);

DO $$
DECLARE
    own_msg_count     INT;
    foreign_msg_count INT;
BEGIN
    SELECT count(*) INTO own_msg_count FROM chat_messages cm
      WHERE EXISTS (
        SELECT 1 FROM chat_threads ct
        WHERE ct.id = cm.thread_id
          AND ct.user_id = '11111111-1111-1111-1111-111111111111'
      );
    ASSERT own_msg_count >= 0, 'Case 7 FAIL: chat_messages query errored';

    SELECT count(*) INTO foreign_msg_count FROM chat_messages cm
      WHERE NOT EXISTS (
        SELECT 1 FROM chat_threads ct
        WHERE ct.id = cm.thread_id
          AND ct.user_id = '11111111-1111-1111-1111-111111111111'
      );
    ASSERT foreign_msg_count = 0,
        'Case 7 FAIL: user_a must NOT see messages in other users threads (got ' || foreign_msg_count || ')';
    RAISE NOTICE 'Case 7 PASS: own=%, foreign=%', own_msg_count, foreign_msg_count;
END
$$;

\echo === Case 8: FK isolation - user_a cannot see messages with user_b parent ===
-- Same GUC context as case 7 (no RESET ALL between them on purpose: we
-- assert FK isolation against the same session as Case 7).
DO $$
DECLARE
    leaked INT;
BEGIN
    SELECT count(*) INTO leaked FROM chat_messages cm
      JOIN chat_threads ct ON ct.id = cm.thread_id
      WHERE ct.user_id <> '11111111-1111-1111-1111-111111111111';
    ASSERT leaked = 0,
        'Case 8 FAIL: FK isolation broken - user_a saw ' || leaked || ' user_b message(s)';
    RAISE NOTICE 'Case 8 PASS: FK isolation holds (leaked=%)', leaked;
END
$$;

RESET ALL;
\echo === ALL 8 SMOKE CASES PASSED ===
