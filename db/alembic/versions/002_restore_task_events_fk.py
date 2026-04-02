"""
002_restore_task_events_fk — Restore FK constraints on alpha_task_events.

alpha_task_events existed before 001_taskgraph ran. CASCADE drop removed its
FK constraints. This migration restores them now that alpha_task_graphs and
alpha_task_steps exist with correct schema.

Revision: 002
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE alpha_task_events
            ADD CONSTRAINT alpha_task_events_graph_id_fkey
            FOREIGN KEY (graph_id)
            REFERENCES alpha_task_graphs(id)
            ON DELETE SET NULL
    """)

    op.execute("""
        ALTER TABLE alpha_task_events
            ADD CONSTRAINT alpha_task_events_step_id_fkey
            FOREIGN KEY (step_id)
            REFERENCES alpha_task_steps(id)
            ON DELETE SET NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE alpha_task_events DROP CONSTRAINT IF EXISTS alpha_task_events_graph_id_fkey")
    op.execute("ALTER TABLE alpha_task_events DROP CONSTRAINT IF EXISTS alpha_task_events_step_id_fkey")
