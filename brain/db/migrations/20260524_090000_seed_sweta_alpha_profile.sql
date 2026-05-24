-- Add Sweta to Alpha family profiles and keep the personal workspace projection complete.

BEGIN;

INSERT INTO alpha_profiles (
    id,
    display_name,
    role,
    child_age,
    max_rating,
    pin_hash,
    active
)
VALUES (
    'sweta',
    'Sweta Gurnani',
    'admin',
    NULL,
    'adult',
    'PLACEHOLDER_SET_BY_KEN',
    true
)
ON CONFLICT (id) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    role = EXCLUDED.role,
    child_age = EXCLUDED.child_age,
    max_rating = EXCLUDED.max_rating,
    active = true;

INSERT INTO alpha_users (id, email, role, is_child, child_age, created_at)
VALUES ('sweta', 'sweta@jarvis.local', 'workspace_admin', false, NULL, now())
ON CONFLICT (id) DO UPDATE SET
    role = EXCLUDED.role,
    is_child = EXCLUDED.is_child,
    child_age = EXCLUDED.child_age;

INSERT INTO alpha_workspace_users (workspace_id, user_id, role, created_at)
SELECT 'personal', 'sweta', 'admin', now()
WHERE EXISTS (SELECT 1 FROM alpha_workspaces WHERE id = 'personal')
ON CONFLICT (workspace_id, user_id) DO UPDATE SET
    role = EXCLUDED.role;

COMMIT;
