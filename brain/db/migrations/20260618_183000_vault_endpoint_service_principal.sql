-- 20260618_183000_vault_endpoint_service_principal.sql
--
-- Seed the Endpoint service principal used by TalentOps Alpha vault uploads.
-- Vault documents keep uploaded_by as the JWT subject for auditability; the
-- subject must exist in alpha_users to satisfy the existing FK.

BEGIN;

INSERT INTO public.alpha_users (id, email, role, is_child, child_age, created_at)
VALUES
    (
        'endpoint_service',
        'endpoint_service@jarvis.local',
        'workspace_user',
        false,
        NULL,
        now()
    )
ON CONFLICT (id) DO UPDATE SET
    email = EXCLUDED.email,
    role = EXCLUDED.role,
    is_child = EXCLUDED.is_child,
    child_age = EXCLUDED.child_age;

INSERT INTO public.alpha_workspace_users (workspace_id, user_id, role, created_at)
SELECT 'personal', 'endpoint_service', 'member', now()
WHERE EXISTS (SELECT 1 FROM public.alpha_workspaces WHERE id = 'personal')
ON CONFLICT (workspace_id, user_id) DO UPDATE SET
    role = EXCLUDED.role;

COMMIT;
