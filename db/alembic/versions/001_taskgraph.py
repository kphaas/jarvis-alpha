"""
001_taskgraph — Drop legacy tables, create alpha_task_graphs + alpha_task_steps.

Revision: 001
"""

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS execution_state CASCADE")
    op.execute("DROP TABLE IF EXISTS task_steps CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_tasks CASCADE")

    op.execute("""
        CREATE TABLE IF NOT EXISTS alpha_task_graphs (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            title               TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'pending'
                                CHECK (status IN (
                                    'pending','running','completed',
                                    'failed','interrupted'
                                )),
            priority            INTEGER NOT NULL DEFAULT 3,
            created_by          UUID NOT NULL,
            workspace_id        TEXT REFERENCES alpha_projects(project_id),
            parent_graph_id     UUID REFERENCES alpha_task_graphs(id),
            checkpoint_step_id  UUID,
            started_at          TIMESTAMP,
            completed_at        TIMESTAMP,
            interrupted_at      TIMESTAMP,
            metadata            JSONB DEFAULT '{}',
            created_at          TIMESTAMP DEFAULT NOW(),
            updated_at          TIMESTAMP DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS alpha_task_steps (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            graph_id            UUID NOT NULL REFERENCES alpha_task_graphs(id) ON DELETE CASCADE,
            step_type           TEXT NOT NULL
                                CHECK (step_type IN (
                                    'llm','code','tool','human_approval',
                                    'memory_read','memory_write','subgraph','notification'
                                )),
            step_index          INTEGER NOT NULL,
            status              TEXT NOT NULL DEFAULT 'pending'
                                CHECK (status IN (
                                    'pending','running','completed','failed',
                                    'interrupted','awaiting_approval'
                                )),
            input               JSONB DEFAULT '{}',
            output              JSONB DEFAULT '{}',
            error               TEXT,
            agent_label         TEXT,
            model_used          TEXT,
            tokens_used         INTEGER,
            requires_approval   BOOLEAN NOT NULL DEFAULT FALSE,
            approved_by         TEXT,
            approved_at         TIMESTAMP,
            started_at          TIMESTAMP,
            completed_at        TIMESTAMP,
            retry_count         INTEGER NOT NULL DEFAULT 0,
            created_at          TIMESTAMP DEFAULT NOW()
        )
    """)

    op.execute("""
        ALTER TABLE alpha_task_graphs
            ADD CONSTRAINT fk_checkpoint_step
            FOREIGN KEY (checkpoint_step_id)
            REFERENCES alpha_task_steps(id)
            DEFERRABLE INITIALLY DEFERRED
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_task_graphs_status   ON alpha_task_graphs(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_task_graphs_created_by ON alpha_task_graphs(created_by)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_task_steps_graph     ON alpha_task_steps(graph_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_task_steps_status    ON alpha_task_steps(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_task_steps_type      ON alpha_task_steps(step_type)")

    op.execute("ALTER TABLE alpha_task_graphs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE alpha_task_steps  ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY graph_isolation ON alpha_task_graphs
            USING (created_by::text = current_setting('jarvis.current_user', true))
    """)

    op.execute("""
        CREATE POLICY step_isolation ON alpha_task_steps
            USING (graph_id IN (
                SELECT id FROM alpha_task_graphs
                WHERE created_by::text = current_setting('jarvis.current_user', true)
            ))
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS alpha_task_steps CASCADE")
    op.execute("DROP TABLE IF EXISTS alpha_task_graphs CASCADE")
