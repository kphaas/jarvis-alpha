-- 007_node_registry.sql
-- Node registry for mesh topology and health checks

BEGIN;

CREATE TABLE IF NOT EXISTS alpha_node_registry (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    role            TEXT NOT NULL,
    node_type       TEXT NOT NULL CHECK (node_type IN ('service', 'storage', 'dev', 'network', 'mobile')),
    tailscale_ip    TEXT,
    health_endpoint TEXT,
    cert_issued_at  TIMESTAMPTZ,
    cert_expires_at TIMESTAMPTZ,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_node_registry_name
    ON alpha_node_registry(name);

CREATE INDEX IF NOT EXISTS idx_node_registry_active
    ON alpha_node_registry(is_active);

-- ── Seed nodes ─────────────────────────────────────────────────────
INSERT INTO alpha_node_registry
    (name, display_name, role, node_type, tailscale_ip, health_endpoint, cert_issued_at, cert_expires_at)
VALUES
    (
        'brain', 'Brain', 'Orchestration · Postgres · Ollama · Memory',
        'service', '100.64.166.22',
        'https://100.64.166.22:8186/health',
        '2026-03-18 00:00:00+00', '2026-06-18 00:00:00+00'
    ),
    (
        'gateway', 'Gateway', 'Internet egress · Claude proxy · MCP · Overnight agent',
        'service', '100.112.63.25',
        'https://jarvis-gateway.tail40ed36.ts.net:8282/health',
        '2026-03-18 00:00:00+00', '2026-06-18 00:00:00+00'
    ),
    (
        'endpoint', 'Endpoint', 'Dashboard · Voice UI · Avatar · TTS',
        'service', '100.87.223.31',
        'https://jarvis-endpoint.tail40ed36.ts.net:4100',
        '2026-03-18 00:00:00+00', '2026-06-18 00:00:00+00'
    ),
    (
        'unraid', 'Unraid NAS', 'NAS · Backup · Docker · Plex',
        'storage', '100.70.174.103',
        NULL, NULL, NULL
    ),
    (
        'iphone', 'iPhone', 'Mobile client',
        'mobile', '100.99.67.25',
        NULL, NULL, NULL
    )
ON CONFLICT (name) DO NOTHING;

COMMIT;
