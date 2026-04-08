ALTER TABLE alpha_buddy_events ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE alpha_buddy_events ADD COLUMN IF NOT EXISTS payload JSONB;
