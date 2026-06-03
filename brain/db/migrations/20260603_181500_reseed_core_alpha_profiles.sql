-- Re-seed core Alpha profiles if the table exists but rows are missing.
--
-- This is intentionally non-destructive:
--   - missing rows are inserted with the same placeholder PIN semantics used
--     by 009_child_profiles.sql;
--   - existing rows keep their current pin_hash, including real bcrypt hashes.

BEGIN;

INSERT INTO public.alpha_profiles (
    id,
    display_name,
    role,
    child_age,
    max_rating,
    pin_hash,
    active
)
VALUES
    ('ken', 'Ken', 'admin', NULL, 'adult', 'PLACEHOLDER_MIGRATE_FROM_ALPHA_PIN', true),
    ('ryleigh', 'Ryleigh', 'child', 8, 'age_8_plus', 'PLACEHOLDER_SET_BY_KEN', true),
    ('sloane', 'Sloane', 'child', 5, 'all_ages', 'PLACEHOLDER_SET_BY_KEN', true)
ON CONFLICT (id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    role = EXCLUDED.role,
    child_age = EXCLUDED.child_age,
    max_rating = EXCLUDED.max_rating,
    active = true;

INSERT INTO public.alpha_users (id, email, role, is_child, child_age, created_at)
VALUES
    ('ken', 'ken@jarvis.local', 'workspace_admin', false, NULL, now()),
    ('ryleigh', 'ryleigh@jarvis.local', 'child', true, 8, now()),
    ('sloane', 'sloane@jarvis.local', 'child', true, 5, now())
ON CONFLICT (id) DO UPDATE SET
    role = EXCLUDED.role,
    is_child = EXCLUDED.is_child,
    child_age = EXCLUDED.child_age;

INSERT INTO public.alpha_workspace_users (workspace_id, user_id, role, created_at)
SELECT 'personal', profile_id, workspace_role, now()
FROM (
    VALUES
        ('ken', 'admin'),
        ('ryleigh', 'member'),
        ('sloane', 'member')
) AS core_profiles(profile_id, workspace_role)
WHERE EXISTS (SELECT 1 FROM public.alpha_workspaces WHERE id = 'personal')
ON CONFLICT (workspace_id, user_id) DO UPDATE SET
    role = EXCLUDED.role;

COMMIT;
