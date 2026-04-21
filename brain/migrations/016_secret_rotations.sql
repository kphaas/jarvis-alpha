CREATE TABLE IF NOT EXISTS alpha_secret_rotations (
    id              SERIAL PRIMARY KEY,
    secret_name     TEXT NOT NULL,
    rotated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    rotated_by      TEXT NOT NULL,
    rotation_days   INTEGER NOT NULL CHECK (rotation_days > 0),
    next_due_at     TIMESTAMPTZ GENERATED ALWAYS AS (rotated_at + (rotation_days || ' days')::interval) STORED,
    nodes_updated   TEXT[] NOT NULL,
    services_restarted TEXT[] NOT NULL,
    verify_status   TEXT NOT NULL CHECK (verify_status IN ('passed','failed','skipped')),
    value_hash      TEXT,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_secret_rotations_name_time 
  ON alpha_secret_rotations(secret_name, rotated_at DESC);

CREATE INDEX IF NOT EXISTS idx_secret_rotations_due 
  ON alpha_secret_rotations(next_due_at);

CREATE OR REPLACE VIEW v_secret_rotation_status AS
SELECT DISTINCT ON (secret_name)
    secret_name,
    rotated_at AS last_rotated_at,
    rotation_days,
    next_due_at,
    GREATEST(0, EXTRACT(DAY FROM (next_due_at - now()))::int) AS days_until_due,
    verify_status AS last_verify_status
FROM alpha_secret_rotations
ORDER BY secret_name, rotated_at DESC;
