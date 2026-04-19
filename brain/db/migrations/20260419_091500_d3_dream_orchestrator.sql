-- D3.1: Dream Orchestrator schema migration
-- Adds Temporal workflow linkage + replan tracking to alpha_dream_sessions
-- Per docs/D3_ORCHESTRATOR_DESIGN.md (commit 0ca12f1)
--
-- Changes:
--   1. temporal_workflow_id TEXT UNIQUE — links DB row to Temporal workflow execution
--   2. temporal_run_id TEXT — current Temporal run ID (changes on retry/continue-as-new)
--   3. replan_count INTEGER NOT NULL DEFAULT 0 — tracks revision loop iterations (max 2)
--   4. Index on temporal_workflow_id for fast orchestrator lookup
--
-- Nullable by design: existing pre-Temporal rows (if any) keep NULL.
-- Orchestrator code enforces NOT NULL at write time via Python layer.

BEGIN;

ALTER TABLE alpha_dream_sessions
  ADD COLUMN IF NOT EXISTS temporal_workflow_id TEXT UNIQUE,
  ADD COLUMN IF NOT EXISTS temporal_run_id TEXT,
  ADD COLUMN IF NOT EXISTS replan_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_dream_sessions_temporal_workflow
  ON alpha_dream_sessions (temporal_workflow_id);

COMMENT ON COLUMN alpha_dream_sessions.temporal_workflow_id IS
  'Temporal workflow execution ID. Links DB row to durable workflow state. One per session.';

COMMENT ON COLUMN alpha_dream_sessions.temporal_run_id IS
  'Current Temporal run ID. Changes on workflow retry or continue-as-new.';

COMMENT ON COLUMN alpha_dream_sessions.replan_count IS
  'Count of planner replan iterations triggered by reviewer NEEDS_REVISION. Max 2 per D3 design.';

COMMIT;
