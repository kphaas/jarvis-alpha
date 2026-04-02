CREATE TABLE IF NOT EXISTS alpha_buddy_events (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    TEXT,
  event_type TEXT NOT NULL CHECK (
    event_type IN ('alert','reminder','suggestion','system')
  ),
  title      TEXT NOT NULL,
  body       TEXT,
  priority   INT NOT NULL DEFAULT 2,
  read       BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_buddy_events_user
  ON alpha_buddy_events (user_id, read, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_buddy_events_unread
  ON alpha_buddy_events (read, created_at DESC)
  WHERE read = false;
