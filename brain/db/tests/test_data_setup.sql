-- =====================================================================
-- test_data_setup.sql — Slab 5.5 RLS smoke harness fixtures
--
-- Purpose: idempotent seed for the test database (jarvis_alpha_test).
--          Provides the four users, one workspace, two chat threads,
--          and at least two messages per thread that the smoke harness
--          (rls_smoke.sql) asserts against.
--
-- Idempotency: every INSERT uses ON CONFLICT DO NOTHING. Wrapped in a
--              single BEGIN/COMMIT so a failure rolls back the partial
--              seed. Safe to re-run.
--
-- Schema notes (verified from brain/db/schema.sql + db/postgres_schema.sql):
--   * alpha_users.id           is TEXT (not UUID). UUID-formatted
--                              strings are stored as text — no cast needed.
--   * alpha_workspaces.id      is TEXT. We use the UUID-formatted
--                              workspace id requested by the spec.
--   * alpha_workspace_users    has FKs to alpha_users(id) and
--                              alpha_workspaces(id), so users + workspace
--                              MUST exist before linking rows.
--   * chat_threads.id          is UUID; chat_threads.user_id is TEXT.
--   * chat_messages.thread_id  is UUID, FK to chat_threads(id).
--   * chat_threads.content_rating and chat_messages.content_rating have
--     CHECK constraints: ('all_ages','age_8_plus','teen','adult').
--   * chat_messages.role       has CHECK ('user','assistant','system').
--
-- Reserved UUIDs (per Slab 5.5 handoff):
--   00000000-0000-0000-0000-000000000001  test_admin    (platform_admin)
--   11111111-1111-1111-1111-111111111111  test_user_a   (user)
--   11111111-1111-1111-1111-111111111112  test_user_b   (user)
--   22222222-2222-2222-2222-222222222222  test_child    (child, age_8_plus)
--   00000000-0000-0000-0000-0000000000aa  test workspace
--
-- TODO (verify-in-morning):
--   * The Slab 3 canonical Shape A template casts current_setting('rls.user_id')
--     to ::uuid, but production chat_threads.user_id is TEXT. Slab 6 will
--     either rewrite the column to UUID or change the cast. Until then the
--     active policy (015_chat_rls_fix.sql) compares as TEXT, so the seeded
--     UUID-formatted strings match correctly.
--   * alpha_users has no `max_rating` column. The child's max_rating
--     (age_8_plus) is a SESSION GUC value set by the smoke harness via
--     SELECT set_config('rls.max_rating', 'age_8_plus', false). Stored
--     here only as a comment for clarity.
--   * chat_threads.owner_profile is FK -> alpha_profiles(id). We leave it
--     NULL on test rows (column is nullable) to avoid pulling in the
--     alpha_profiles fixture chain.
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. Workspace (must exist before alpha_workspace_users rows)
-- ---------------------------------------------------------------------
INSERT INTO alpha_workspaces (id, name, slug, enabled, config, created_at)
VALUES (
    '00000000-0000-0000-0000-0000000000aa',
    'RLS Smoke Test Workspace',
    'rls-smoke-test',
    true,
    '{"description": "Slab 5.5 smoke harness fixture — not for production use"}'::jsonb,
    now()
)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------
-- 2. Users (4 fixtures: admin, user_a, user_b, child)
-- ---------------------------------------------------------------------
INSERT INTO alpha_users (id, email, role, is_child, child_age, created_at)
VALUES
    ('00000000-0000-0000-0000-000000000001',
     'test_admin@example.com',
     'platform_admin',
     false,
     NULL,
     now()),
    ('11111111-1111-1111-1111-111111111111',
     'test_user_a@example.com',
     'user',
     false,
     NULL,
     now()),
    ('11111111-1111-1111-1111-111111111112',
     'test_user_b@example.com',
     'user',
     false,
     NULL,
     now()),
    ('22222222-2222-2222-2222-222222222222',
     'test_child@example.com',
     'child',
     true,
     8,
     now())
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------
-- 3. Workspace membership (link all 4 users to test workspace)
-- ---------------------------------------------------------------------
INSERT INTO alpha_workspace_users (workspace_id, user_id, role, created_at)
VALUES
    ('00000000-0000-0000-0000-0000000000aa',
     '00000000-0000-0000-0000-000000000001',
     'admin',
     now()),
    ('00000000-0000-0000-0000-0000000000aa',
     '11111111-1111-1111-1111-111111111111',
     'member',
     now()),
    ('00000000-0000-0000-0000-0000000000aa',
     '11111111-1111-1111-1111-111111111112',
     'member',
     now()),
    ('00000000-0000-0000-0000-0000000000aa',
     '22222222-2222-2222-2222-222222222222',
     'member',
     now())
ON CONFLICT (workspace_id, user_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- 4. Chat threads — one owned by user_a, one owned by user_b
--    Fixed UUIDs so re-runs ON CONFLICT DO NOTHING. Content rating
--    'adult' on user_a, 'age_8_plus' on user_b so Case 3 (child rating)
--    has both above-ceiling and below-ceiling rows.
-- ---------------------------------------------------------------------
INSERT INTO chat_threads (id, user_id, title, mode, content_rating, created_at, updated_at)
VALUES
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1',
     '11111111-1111-1111-1111-111111111111',
     'user_a smoke thread (adult)',
     'realtime',
     'adult',
     now(),
     now()),
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1',
     '11111111-1111-1111-1111-111111111112',
     'user_b smoke thread (age_8_plus)',
     'realtime',
     'age_8_plus',
     now(),
     now())
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------
-- 5. Chat messages — at least 2 per thread
--    Mix of user / assistant roles per chat_messages.role CHECK.
--    content_rating mirrored from parent thread for case 3 / 7 / 8.
-- ---------------------------------------------------------------------
INSERT INTO chat_messages (id, thread_id, role, content, content_rating, created_at)
VALUES
    -- user_a thread (adult)
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaa01',
     'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1',
     'user',
     'user_a message 1 — adult content',
     'adult',
     now()),
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaa02',
     'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1',
     'assistant',
     'user_a assistant reply 1',
     'adult',
     now()),
    -- user_b thread (age_8_plus)
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbb01',
     'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1',
     'user',
     'user_b message 1 — age 8 plus',
     'age_8_plus',
     now()),
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbb02',
     'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1',
     'assistant',
     'user_b assistant reply 1',
     'age_8_plus',
     now())
ON CONFLICT (id) DO NOTHING;

COMMIT;

\echo === test_data_setup.sql complete ===
