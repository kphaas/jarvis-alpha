-- Migration 011: Tiered power tracking

-- Raw 15-minute samples — purged after 30 days by Buddy
CREATE TABLE IF NOT EXISTS alpha_power_readings (
    id          BIGSERIAL PRIMARY KEY,
    node_name   TEXT NOT NULL,
    watts       NUMERIC(8,3) NOT NULL,
    cpu_pct     NUMERIC(5,2),
    source      TEXT DEFAULT 'psutil' CHECK (source IN ('powermetrics','psutil','static')),
    recorded_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_power_readings_node_time
    ON alpha_power_readings(node_name, recorded_at DESC);

-- Hourly averages — kept 12 months, rolled up by Buddy
CREATE TABLE IF NOT EXISTS alpha_power_hourly (
    id          BIGSERIAL PRIMARY KEY,
    node_name   TEXT NOT NULL,
    hour_start  TIMESTAMPTZ NOT NULL,
    avg_watts   NUMERIC(8,3) NOT NULL,
    sample_count INTEGER DEFAULT 0,
    UNIQUE (node_name, hour_start)
);

CREATE INDEX IF NOT EXISTS idx_power_hourly_node_time
    ON alpha_power_hourly(node_name, hour_start DESC);

-- Daily averages — kept 5 years, rolled up by Buddy
CREATE TABLE IF NOT EXISTS alpha_power_daily (
    id          BIGSERIAL PRIMARY KEY,
    node_name   TEXT NOT NULL,
    day_start   DATE NOT NULL,
    avg_watts   NUMERIC(8,3) NOT NULL,
    sample_count INTEGER DEFAULT 0,
    UNIQUE (node_name, day_start)
);

CREATE INDEX IF NOT EXISTS idx_power_daily_node_time
    ON alpha_power_daily(node_name, day_start DESC);
