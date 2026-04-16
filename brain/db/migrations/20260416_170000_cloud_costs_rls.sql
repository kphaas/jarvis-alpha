-- TD-65: Add RLS to alpha_cloud_costs
-- Pattern: platform_admin for ALL (read + write)
-- FORCE RLS deferred to Stage 6 atomic migration

BEGIN;

ALTER TABLE alpha_cloud_costs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS cloud_costs_isolation ON alpha_cloud_costs;
CREATE POLICY cloud_costs_isolation ON alpha_cloud_costs
    FOR ALL
    USING  (current_setting('jarvis.role', true) = 'platform_admin')
    WITH CHECK (current_setting('jarvis.role', true) = 'platform_admin');

COMMENT ON POLICY cloud_costs_isolation ON alpha_cloud_costs
    IS 'Admin-only access to cloud cost records. Superuser (jarvisbrain) bypasses until FORCE RLS in Stage 6.';

COMMIT;
