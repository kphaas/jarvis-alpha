-- =============================================================================
-- Migration: Audit stream view + source_request_id indexes
-- =============================================================================
-- Creates unified alpha_audit_stream view across 4 audit tables for
-- CloudTrail-style call chain forensics. All views use security_invoker=true
-- to enforce caller's RLS policies (Postgres 15+ feature).
--
-- Access: View is admin-only — restricted via explicit platform_admin check
-- at the view level, overriding permissive underlying table policies for
-- consistent audit-stream behavior.
--
-- Depends on: 20260416_080000_audit_attribution_columns.sql (adds the
--             executor/on_behalf_of/source_request_id/schema_version columns)
--
-- Index strategy: Non-concurrent CREATE INDEX is used because:
--   1. apply_migrations.sh wraps each file in a single transaction (-1 flag)
--      which forbids CONCURRENTLY.
--   2. source_request_id columns are brand-new and NULL for all existing
--      rows, so partial indexes build in sub-millisecond on empty data.
--   3. Lock contention is zero at index build time.
--
-- Design references:
--   AWS CloudTrail audit stream: admin-only access, normalized schema
--   Google Cloud Audit Logs: per-service projection to common LogEntry schema
--   Postgres security_invoker views (PG15+): RLS pass-through to caller

BEGIN;

-- =============================================================================
-- Partial indexes on source_request_id — correlation query support
-- =============================================================================
-- Pattern: WHERE source_request_id IS NOT NULL
-- Rationale: Historical rows are all NULL; full btree would waste space on
--   NULL entries. Partial index is smaller, faster, identical query perf.

CREATE INDEX IF NOT EXISTS idx_approval_audit_request_id
  ON alpha_approval_audit (source_request_id)
  WHERE source_request_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_task_events_request_id
  ON alpha_task_events (source_request_id)
  WHERE source_request_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_cloud_costs_request_id
  ON alpha_cloud_costs (source_request_id)
  WHERE source_request_id IS NOT NULL;

-- alpha_watchdog_events uses its pre-existing trace_id UUID column instead.
-- Index on trace_id if one doesn't already exist:

CREATE INDEX IF NOT EXISTS idx_watchdog_events_trace_id
  ON alpha_watchdog_events (trace_id)
  WHERE trace_id IS NOT NULL;


-- =============================================================================
-- Per-table intermediate views — project native schema to common shape
-- =============================================================================
-- Common shape:
--   ts TIMESTAMPTZ, executor TEXT, on_behalf_of TEXT, source_request_id TEXT,
--   action TEXT, resource_type TEXT, resource_id TEXT, result TEXT,
--   metadata JSONB, schema_version SMALLINT
--
-- All views use security_invoker=true so caller's RLS policies apply.

DROP VIEW IF EXISTS alpha_audit_stream;
DROP VIEW IF EXISTS v_audit_approval;
DROP VIEW IF EXISTS v_audit_tasks;
DROP VIEW IF EXISTS v_audit_watchdog;
DROP VIEW IF EXISTS v_audit_cloud_costs;

CREATE VIEW v_audit_approval
  WITH (security_invoker = true) AS
  SELECT
    decided_at                AS ts,
    executor,
    on_behalf_of,
    source_request_id,
    decision                  AS action,
    'approval'::text          AS resource_type,
    approval_id::text         AS resource_id,
    decision                  AS result,
    jsonb_build_object(
      'action_class', action_class,
      'risk_tier', risk_tier,
      'actor_sub', actor_sub,
      'actor_type', actor_type,
      'description', description,
      'parameters_hash', parameters_hash,
      'decided_by', decided_by,
      'overnight', overnight
    )                         AS metadata,
    schema_version
  FROM alpha_approval_audit;

CREATE VIEW v_audit_tasks
  WITH (security_invoker = true) AS
  SELECT
    created_at                AS ts,
    executor,
    on_behalf_of,
    source_request_id,
    event_type                AS action,
    'task'::text              AS resource_type,
    COALESCE(step_id::text, graph_id::text)  AS resource_id,
    severity                  AS result,
    jsonb_build_object(
      'graph_id', graph_id,
      'step_id', step_id,
      'message', message,
      'title', title,
      'source', source,
      'read', read
    ) || COALESCE(detail, '{}'::jsonb)  AS metadata,
    schema_version
  FROM alpha_task_events;

CREATE VIEW v_audit_watchdog
  WITH (security_invoker = true) AS
  SELECT
    created_at                AS ts,
    executor,
    on_behalf_of,
    trace_id::text            AS source_request_id,
    event_type                AS action,
    'service'::text           AS resource_type,
    service_name              AS resource_id,
    current_state             AS result,
    jsonb_build_object(
      'service_name', service_name,
      'node', node,
      'previous_state', previous_state,
      'current_state', current_state,
      'consecutive_failures', consecutive_failures,
      'latency_ms', latency_ms,
      'http_status', http_status,
      'error_message', error_message,
      'action_taken', action_taken
    )                         AS metadata,
    schema_version
  FROM alpha_watchdog_events;

CREATE VIEW v_audit_cloud_costs
  WITH (security_invoker = true) AS
  SELECT
    created_at                AS ts,
    executor,
    on_behalf_of,
    source_request_id,
    'cloud_call'::text        AS action,
    'cloud_api'::text         AS resource_type,
    provider || ':' || model  AS resource_id,
    CASE WHEN cost_usd > 0 THEN 'billed' ELSE 'free' END  AS result,
    jsonb_build_object(
      'provider', provider,
      'model', model,
      'prompt_tokens', prompt_tokens,
      'completion_tokens', completion_tokens,
      'total_tokens', total_tokens,
      'cost_usd', cost_usd,
      'session_type', session_type,
      'key_name', key_name,
      'intent', intent
    )                         AS metadata,
    schema_version
  FROM alpha_cloud_costs;


-- =============================================================================
-- Unified audit stream view — admin-only access
-- =============================================================================
-- Explicit platform_admin check at view level for consistent behavior across
-- underlying tables with different RLS strictness. Non-admin callers get zero
-- rows regardless of underlying table policies.

CREATE VIEW alpha_audit_stream
  WITH (security_invoker = true) AS
  SELECT * FROM v_audit_approval
  WHERE current_setting('jarvis.role', true) = 'platform_admin'
  UNION ALL
  SELECT * FROM v_audit_tasks
  WHERE current_setting('jarvis.role', true) = 'platform_admin'
  UNION ALL
  SELECT * FROM v_audit_watchdog
  WHERE current_setting('jarvis.role', true) = 'platform_admin'
  UNION ALL
  SELECT * FROM v_audit_cloud_costs
  WHERE current_setting('jarvis.role', true) = 'platform_admin';


-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON VIEW alpha_audit_stream IS
  'Unified call-chain audit stream across 4 source tables. Admin-only (platform_admin role required). Query by source_request_id for end-to-end forensics: SELECT * FROM alpha_audit_stream WHERE source_request_id=''...'' ORDER BY ts.';

COMMENT ON VIEW v_audit_approval IS
  'Audit stream projection of alpha_approval_audit. security_invoker=true enforces caller RLS.';

COMMENT ON VIEW v_audit_tasks IS
  'Audit stream projection of alpha_task_events. security_invoker=true enforces caller RLS.';

COMMENT ON VIEW v_audit_watchdog IS
  'Audit stream projection of alpha_watchdog_events. Uses pre-existing trace_id UUID aliased as source_request_id. security_invoker=true enforces caller RLS.';

COMMENT ON VIEW v_audit_cloud_costs IS
  'Audit stream projection of alpha_cloud_costs. security_invoker=true enforces caller RLS. Note: this table has no RLS today — admin-only check at alpha_audit_stream view level is the access boundary.';

COMMIT;


-- =============================================================================
-- Rollback (run manually if needed):
-- =============================================================================
-- BEGIN;
-- DROP VIEW IF EXISTS alpha_audit_stream;
-- DROP VIEW IF EXISTS v_audit_approval;
-- DROP VIEW IF EXISTS v_audit_tasks;
-- DROP VIEW IF EXISTS v_audit_watchdog;
-- DROP VIEW IF EXISTS v_audit_cloud_costs;
-- DROP INDEX IF EXISTS idx_approval_audit_request_id;
-- DROP INDEX IF EXISTS idx_task_events_request_id;
-- DROP INDEX IF EXISTS idx_cloud_costs_request_id;
-- DROP INDEX IF EXISTS idx_watchdog_events_trace_id;
-- COMMIT;
