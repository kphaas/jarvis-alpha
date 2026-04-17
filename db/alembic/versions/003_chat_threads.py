"""003_chat_threads — chat threads and messages

Revision ID: 003
Revises: 002
Create Date: 2026-04-02
"""

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS chat_threads (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      TEXT NOT NULL,
            title        TEXT NOT NULL DEFAULT 'New conversation',
            mode         TEXT NOT NULL DEFAULT 'realtime'
                             CHECK (mode IN ('realtime','overnight')),
            model_used   TEXT,
            project_id   INTEGER,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            archived_at  TIMESTAMPTZ
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            thread_id        UUID NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
            role             TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
            content          TEXT NOT NULL,
            model_used       TEXT,
            council_detail   JSONB,
            memory_injected  BOOLEAN NOT NULL DEFAULT false,
            latency_ms       INTEGER,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_threads_user ON chat_threads(user_id) WHERE archived_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_thread ON chat_messages(thread_id)"
    )

    op.execute("ALTER TABLE chat_threads ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY")

    op.execute("""
        CREATE POLICY chat_threads_isolation ON chat_threads
        USING (user_id = current_setting('rls.user_id', true))
    """)
    op.execute("""
        CREATE POLICY chat_messages_isolation ON chat_messages
        USING (
            thread_id IN (
                SELECT id FROM chat_threads
                WHERE user_id = current_setting('rls.user_id', true)
            )
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_messages CASCADE")
    op.execute("DROP TABLE IF EXISTS chat_threads CASCADE")
