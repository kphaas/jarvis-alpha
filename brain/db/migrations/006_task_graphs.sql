-- 006_task_graphs.sql
-- TaskGraph engine: DAG-based task execution with retry support

BEGIN;

-- ── Graph table ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alpha_task_graphs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    created_by      TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('manual', 'agent')),
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'running', 'halted', 'complete')),
    ci_required     BOOLEAN NOT NULL DEFAULT FALSE,
    ci_passed       BOOLEAN,
    checkpoint      JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

-- ── Step table ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alpha_task_steps (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    graph_id        UUID NOT NULL REFERENCES alpha_task_graphs(id) ON DELETE CASCADE,
    label           TEXT NOT NULL,
    depends_on      UUID[] NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN (
                            'pending', 'running', 'failed',
                            'retrying', 'complete', 'skipped', 'halted'
                        )),
    retry_count     INT NOT NULL DEFAULT 0 CHECK (retry_count >= 0 AND retry_count <= 3),
    executor        TEXT NOT NULL DEFAULT 'agent'
                        CHECK (executor IN ('agent', 'overnight', 'manual')),
    tool            TEXT,
    input           JSONB NOT NULL DEFAULT '{}',
    output          JSONB,
    error           TEXT,
    checkpoint      JSONB NOT NULL DEFAULT '{}',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

-- ── Indexes ────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_task_graphs_status
    ON alpha_task_graphs(status);

CREATE INDEX IF NOT EXISTS idx_task_graphs_created_by
    ON alpha_task_graphs(created_by);

CREATE INDEX IF NOT EXISTS idx_task_steps_graph_id
    ON alpha_task_steps(graph_id);

CREATE INDEX IF NOT EXISTS idx_task_steps_status
    ON alpha_task_steps(status);

-- ── RLS ────────────────────────────────────────────────────────────
ALTER TABLE alpha_task_graphs ENABLE ROW LEVEL SECURITY;
ALTER TABLE alpha_task_steps  ENABLE ROW LEVEL SECURITY;

CREATE POLICY task_graphs_isolation ON alpha_task_graphs
    USING (
        created_by = current_setting('jarvis.current_user', TRUE)
        OR current_setting('jarvis.role', TRUE) = 'admin'
    );

CREATE POLICY task_steps_isolation ON alpha_task_steps
    USING (
        graph_id IN (
            SELECT id FROM alpha_task_graphs
            WHERE created_by = current_setting('jarvis.current_user', TRUE)
            OR current_setting('jarvis.role', TRUE) = 'admin'
        )
    );

COMMIT;
