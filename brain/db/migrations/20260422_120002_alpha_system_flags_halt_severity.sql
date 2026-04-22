BEGIN;

SET LOCAL jarvis.role = 'platform_admin';

ALTER TABLE alpha_system_flags
    ADD COLUMN IF NOT EXISTS halt_severity TEXT;

ALTER TABLE alpha_system_flags
    DROP CONSTRAINT IF EXISTS alpha_system_flags_halt_severity_check;

ALTER TABLE alpha_system_flags
    ADD CONSTRAINT alpha_system_flags_halt_severity_check
    CHECK (halt_severity IS NULL OR halt_severity IN ('graceful', 'fast', 'emergency'));

COMMENT ON COLUMN alpha_system_flags.halt_severity IS
    'Severity for Dream Mode halt signals. graceful=flush+mark halted (30s grace); fast=flush+mark aborted (5s grace); emergency=mark killed immediately. NULL for non-halt flags.';

UPDATE alpha_system_flags
    SET halt_severity = 'fast'
    WHERE flag_name = 'dream_mode_killed'
      AND halt_severity IS NULL;

INSERT INTO alpha_system_flags (flag_name, flag_value, reason, halt_severity, updated_by)
VALUES (
    'dream_emergency',
    FALSE,
    'Emergency halt — skip all cleanup, mark session killed immediately. Set TRUE only for critical safety violations.',
    'emergency',
    'd3.3_migration'
)
ON CONFLICT (flag_name) DO NOTHING;

COMMIT;
