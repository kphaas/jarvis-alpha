BEGIN;

SET LOCAL jarvis.role = 'platform_admin';

ALTER TABLE alpha_cloud_costs
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

COMMENT ON COLUMN alpha_cloud_costs.idempotency_key IS
    'Deterministic idempotency key for Dream Mode cost writes. Format: dream:<workflow_id>:<activity_type>:<step_id>. Partial unique index prevents duplicate cost rows on activity retry.';

CREATE UNIQUE INDEX IF NOT EXISTS idx_alpha_cloud_costs_idempotency_key
    ON alpha_cloud_costs (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

COMMIT;
