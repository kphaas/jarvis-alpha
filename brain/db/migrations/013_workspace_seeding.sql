-- 013_workspace_seeding.sql
-- Workspace Seeding v1 — establish the household workspace model
-- 
-- Decisions locked (handoff_05):
--   Q1: One workspace 'personal' = household, profiles are members (Slack/Notion model)
--   Q2: Trigger-based sync from alpha_profiles -> alpha_users (atomic projection)
--   Q3: workspace_id will be added to JWT claims via alpha_workspace_users lookup at PIN auth time
--
-- This migration is IDEMPOTENT — safe to re-run.
-- 
-- Source of truth: alpha_profiles
-- Projection target: alpha_users (for Family Vault FK compatibility)

BEGIN;

-- ============================================================================
-- STEP 1: Seed the default 'personal' workspace
-- ============================================================================

INSERT INTO alpha_workspaces (id, name, slug, enabled, config, created_at)
VALUES (
    'personal',
    'Personal',
    'personal',
    true,
    '{"description": "Default household workspace — ken, ryleigh, sloane"}'::jsonb,
    now()
)
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- STEP 2: Create trigger function to mirror alpha_profiles -> alpha_users
-- ============================================================================
-- Why SECURITY DEFINER: trigger runs as table owner (jarvisbrain), bypasses RLS
-- on alpha_users. This is the SECURITY DEFINER pattern locked in handoff_04 for
-- background writes to profile-bearing tables.

CREATE OR REPLACE FUNCTION sync_profile_to_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF (TG_OP = 'INSERT') THEN
        INSERT INTO alpha_users (id, email, role, is_child, child_age, created_at)
        VALUES (
            NEW.id,
            NEW.id || '@jarvis.local',
            CASE WHEN NEW.role = 'admin' THEN 'workspace_admin' ELSE 'workspace_user' END,
            (NEW.role = 'child'),
            NEW.child_age,
            COALESCE(NEW.created_at, now())
        )
        ON CONFLICT (id) DO UPDATE SET
            role = EXCLUDED.role,
            is_child = EXCLUDED.is_child,
            child_age = EXCLUDED.child_age;
        RETURN NEW;
    ELSIF (TG_OP = 'UPDATE') THEN
        UPDATE alpha_users
        SET 
            role = CASE WHEN NEW.role = 'admin' THEN 'workspace_admin' ELSE 'workspace_user' END,
            is_child = (NEW.role = 'child'),
            child_age = NEW.child_age
        WHERE id = NEW.id;
        RETURN NEW;
    ELSIF (TG_OP = 'DELETE') THEN
        DELETE FROM alpha_users WHERE id = OLD.id;
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$;

-- ============================================================================
-- STEP 3: Attach trigger to alpha_profiles
-- ============================================================================

DROP TRIGGER IF EXISTS trg_sync_profile_to_user ON alpha_profiles;

CREATE TRIGGER trg_sync_profile_to_user
AFTER INSERT OR UPDATE OR DELETE ON alpha_profiles
FOR EACH ROW
EXECUTE FUNCTION sync_profile_to_user();

-- ============================================================================
-- STEP 4: Backfill alpha_users from existing alpha_profiles
-- ============================================================================
-- Triggers don't fire for existing rows. Force the projection now.

INSERT INTO alpha_users (id, email, role, is_child, child_age, created_at)
SELECT
    p.id,
    p.id || '@jarvis.local',
    CASE WHEN p.role = 'admin' THEN 'workspace_admin' ELSE 'workspace_user' END,
    (p.role = 'child'),
    p.child_age,
    p.created_at
FROM alpha_profiles p
ON CONFLICT (id) DO UPDATE SET
    role = EXCLUDED.role,
    is_child = EXCLUDED.is_child,
    child_age = EXCLUDED.child_age;

-- ============================================================================
-- STEP 5: Add all profiles as members of the personal workspace
-- ============================================================================

INSERT INTO alpha_workspace_users (workspace_id, user_id, role, created_at)
SELECT
    'personal',
    p.id,
    CASE WHEN p.role = 'admin' THEN 'admin' ELSE 'member' END,
    now()
FROM alpha_profiles p
WHERE p.active = true
ON CONFLICT (workspace_id, user_id) DO NOTHING;

-- ============================================================================
-- STEP 6: Backfill workspace_id on existing alpha_conversation_memory rows
-- ============================================================================
-- The 40 existing memory rows have workspace_id = NULL. Set them to 'personal'.

UPDATE alpha_conversation_memory
SET workspace_id = 'personal'
WHERE workspace_id IS NULL;

COMMIT;

-- ============================================================================
-- Verification (run separately, NOT inside transaction):
-- ============================================================================
-- SELECT * FROM alpha_workspaces;
-- SELECT * FROM alpha_users ORDER BY id;
-- SELECT * FROM alpha_workspace_users ORDER BY user_id;
-- SELECT count(*) FROM alpha_conversation_memory WHERE workspace_id IS NULL;
