-- =============================================================================
-- Migration: Audit attribution columns
-- =============================================================================
-- Adds executor / on_behalf_of / source_request_id / schema_version to 3 audit
-- tables for CloudTrail-style call chain forensics. Plus adds 'dream' to
-- alpha_cloud_costs session_type CHECK constraint.
--
-- NOTE: alpha_watchdog_events ALREADY HAS a trace_id UUID column that serves
-- the same purpose as source_request_id. We add only executor/on_behalf_of/
-- schema_version to watchdog. Views will alias trace_id::TEXT AS
-- source_request_id in the B1b migration.
--
-- This migration is INTENTIONALLY scoped to column adds only.
-- A separate migration (20260416_080001_audit_stream_view.sql) creates the
-- unified view with security_invoker=true.
--
-- Design references:
--   AWS CloudTrail userIdentity: TEXT with fixed value domain
--   Google Cloud Audit Logs: common LogEntry schema projected per-service
--   Stripe Radar: schema_version column for metadata evolution
--
-- Safety:
--   All new columns NULLABLE (no default except schema_version=1).
--   CHECK constraint added NOT VALID to skip historical row scan.
--   Partial indexes on source_request_id are in the B1b migration
--   (CREATE INDEX CONCURRENTLY cannot be inside a transaction).

BEGIN;

-- === alpha_approval_audit ===
-- Immutable audit table (REVOKE DELETE/UPDATE exists). ALTER TABLE succeeds
-- because migration role (jarvisbrain) owns the table — REVOKE affects DML only.

ALTER TABLE alpha_approval_audit
  ADD COLUMN IF NOT EXISTS executor TEXT,
  ADD COLUMN IF NOT EXISTS on_behalf_of TEXT,
  ADD COLUMN IF NOT EXISTS source_request_id TEXT,
  ADD COLUMN IF NOT EXISTS schema_version SMALLINT DEFAULT 1;

ALTER TABLE alpha_approval_audit
  DROP CONSTRAINT IF EXISTS ck_approval_audit_executor;

ALTER TABLE alpha_approval_audit
  ADD CONSTRAINT ck_approval_audit_executor
  CHECK (executor IS NULL OR executor IN
    ('ken', 'dream', 'gateway', 'buddy', 'system', 'forge', 'endpoint', 'sandbox', 'brain'))
  NOT VALID;

COMMENT ON COLUMN alpha_approval_audit.executor IS
  'Node/service that performed the action. Values: ken (human), dream, gateway, buddy, system, forge, endpoint, sandbox, brain. NULL for historical rows pre-2026-04-16.';

COMMENT ON COLUMN alpha_approval_audit.on_behalf_of IS
  'When a service acts on behalf of a human or another service, who authorized it. NULL for direct user actions.';

COMMENT ON COLUMN alpha_approval_audit.source_request_id IS
  'W3C traceparent trace-id (32-hex-char) propagated from originating HTTP request via X-Request-ID header. Enables call chain forensics.';

COMMENT ON COLUMN alpha_approval_audit.schema_version IS
  'Schema version for parameters_hash/actor_sub field interpretation. Increment when schema semantics change. NULL for historical rows.';


-- === alpha_task_events ===

ALTER TABLE alpha_task_events
  ADD COLUMN IF NOT EXISTS executor TEXT,
  ADD COLUMN IF NOT EXISTS on_behalf_of TEXT,
  ADD COLUMN IF NOT EXISTS source_request_id TEXT,
  ADD COLUMN IF NOT EXISTS schema_version SMALLINT DEFAULT 1;

ALTER TABLE alpha_task_events
  DROP CONSTRAINT IF EXISTS ck_task_events_executor;

ALTER TABLE alpha_task_events
  ADD CONSTRAINT ck_task_events_executor
  CHECK (executor IS NULL OR executor IN
    ('ken', 'dream', 'gateway', 'buddy', 'system', 'forge', 'endpoint', 'sandbox', 'brain'))
  NOT VALID;

COMMENT ON COLUMN alpha_task_events.executor IS
  'Node/service that emitted the event. See alpha_approval_audit.executor for value domain.';

COMMENT ON COLUMN alpha_task_events.on_behalf_of IS
  'When a service acts on behalf of a human or another service, who authorized it.';

COMMENT ON COLUMN alpha_task_events.source_request_id IS
  'W3C traceparent trace-id propagated from the originating HTTP request.';

COMMENT ON COLUMN alpha_task_events.schema_version IS
  'Schema version for detail JSONB field interpretation.';


-- === alpha_watchdog_events ===
-- NOTE: This table already has trace_id UUID column. We do NOT add
-- source_request_id here. The audit_stream view will alias:
--   trace_id::TEXT AS source_request_id

ALTER TABLE alpha_watchdog_events
  ADD COLUMN IF NOT EXISTS executor TEXT,
  ADD COLUMN IF NOT EXISTS on_behalf_of TEXT,
  ADD COLUMN IF NOT EXISTS schema_version SMALLINT DEFAULT 1;

ALTER TABLE alpha_watchdog_events
  DROP CONSTRAINT IF EXISTS ck_watchdog_events_executor;

ALTER TABLE alpha_watchdog_events
  ADD CONSTRAINT ck_watchdog_events_executor
  CHECK (executor IS NULL OR executor IN
    ('ken', 'dream', 'gateway', 'buddy', 'system', 'forge', 'endpoint', 'sandbox', 'brain'))
  NOT VALID;

COMMENT ON COLUMN alpha_watchdog_events.executor IS
  'Node/service that triggered the watchdog event. Typically watchdog agent itself. See alpha_approval_audit.executor for value domain.';

COMMENT ON COLUMN alpha_watchdog_events.on_behalf_of IS
  'When a service acts on behalf of another service during restart/recovery, who authorized it.';

COMMENT ON COLUMN alpha_watchdog_events.schema_version IS
  'Schema version for event_type/action_taken field interpretation.';


-- === alpha_cloud_costs ===
-- Expand session_type CHECK to include 'dream'. Keep 'overnight' for backward
-- compat. Dream Mode writes will use session_type='dream' going forward.

ALTER TABLE alpha_cloud_costs
  ADD COLUMN IF NOT EXISTS executor TEXT,
  ADD COLUMN IF NOT EXISTS on_behalf_of TEXT,
  ADD COLUMN IF NOT EXISTS source_request_id TEXT,
  ADD COLUMN IF NOT EXISTS schema_version SMALLINT DEFAULT 1;

ALTER TABLE alpha_cloud_costs
  DROP CONSTRAINT IF EXISTS alpha_cloud_costs_session_type_check;

ALTER TABLE alpha_cloud_costs
  ADD CONSTRAINT alpha_cloud_costs_session_type_check
  CHECK (session_type IS NULL OR session_type IN
    ('ask', 'overnight', 'forge', 'other', 'dream'));

ALTER TABLE alpha_cloud_costs
  DROP CONSTRAINT IF EXISTS ck_cloud_costs_executor;

ALTER TABLE alpha_cloud_costs
  ADD CONSTRAINT ck_cloud_costs_executor
  CHECK (executor IS NULL OR executor IN
    ('ken', 'dream', 'gateway', 'buddy', 'system', 'forge', 'endpoint', 'sandbox', 'brain'))
  NOT VALID;

COMMENT ON COLUMN alpha_cloud_costs.executor IS
  'Node/service that initiated the cloud call. Typically gateway (adapter invocation) or dream (overnight orchestrator).';

COMMENT ON COLUMN alpha_cloud_costs.on_behalf_of IS
  'Who authorized the cloud call. ken for direct requests, dream for overnight batches, system for infrastructure checks.';

COMMENT ON COLUMN alpha_cloud_costs.source_request_id IS
  'W3C traceparent trace-id. Enables end-to-end attribution from UI click through adapter call.';

COMMENT ON COLUMN alpha_cloud_costs.schema_version IS
  'Schema version for intent/key_name field interpretation.';


COMMIT;


-- =============================================================================
-- Rollback (if needed, run manually):
-- =============================================================================
-- BEGIN;
-- ALTER TABLE alpha_approval_audit DROP CONSTRAINT IF EXISTS ck_approval_audit_executor;
-- ALTER TABLE alpha_approval_audit DROP COLUMN IF EXISTS executor,
--   DROP COLUMN IF EXISTS on_behalf_of, DROP COLUMN IF EXISTS source_request_id,
--   DROP COLUMN IF EXISTS schema_version;
-- ALTER TABLE alpha_task_events DROP CONSTRAINT IF EXISTS ck_task_events_executor;
-- ALTER TABLE alpha_task_events DROP COLUMN IF EXISTS executor,
--   DROP COLUMN IF EXISTS on_behalf_of, DROP COLUMN IF EXISTS source_request_id,
--   DROP COLUMN IF EXISTS schema_version;
-- ALTER TABLE alpha_watchdog_events DROP CONSTRAINT IF EXISTS ck_watchdog_events_executor;
-- ALTER TABLE alpha_watchdog_events DROP COLUMN IF EXISTS executor,
--   DROP COLUMN IF EXISTS on_behalf_of, DROP COLUMN IF EXISTS schema_version;
-- ALTER TABLE alpha_cloud_costs DROP CONSTRAINT IF EXISTS ck_cloud_costs_executor;
-- ALTER TABLE alpha_cloud_costs DROP CONSTRAINT IF EXISTS alpha_cloud_costs_session_type_check;
-- ALTER TABLE alpha_cloud_costs ADD CONSTRAINT alpha_cloud_costs_session_type_check
--   CHECK (session_type IS NULL OR session_type IN ('ask', 'overnight', 'forge', 'other'));
-- ALTER TABLE alpha_cloud_costs DROP COLUMN IF EXISTS executor,
--   DROP COLUMN IF EXISTS on_behalf_of, DROP COLUMN IF EXISTS source_request_id,
--   DROP COLUMN IF EXISTS schema_version;
-- COMMIT;

