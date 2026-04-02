-- 008_fix_gateway_health_url.sql
-- Corrects Gateway health_endpoint seeded by 007 with wrong port (:8282 → :8283)
UPDATE alpha_node_registry
SET health_endpoint = 'https://jarvis-gateway.tail40ed36.ts.net:8283/health'
WHERE name = 'gateway';
