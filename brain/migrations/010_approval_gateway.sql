-- Migration 010: Approval Gateway tables
-- Run on Brain: /opt/homebrew/Cellar/postgresql@16/16.13/bin/psql -d jarvis_alpha -f brain/migrations/010_approval_gateway.sql

BEGIN;

-- 1. Approval queue — pending actions awaiting human decision
CREATE TABLE IF NOT EXISTS alpha_approval_queue (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action_class       TEXT[] NOT NULL,
    risk_tier          TEXT NOT NULL CHECK (risk_tier IN ('T1','T2','T3','T4','T5')),
    actor_sub          TEXT NOT NULL,
    actor_type         TEXT NOT NULL CHECK (actor_type IN ('user','service','agent')),
    actor_node         TEXT,
    description        TEXT NOT NULL,
    parameters_hash    TEXT NOT NULL,
    parameters_preview TEXT,
    nonce              TEXT NOT NULL UNIQUE,
    notification_sent  BOOLEAN NOT NULL DEFAULT false,
    status             TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending','approved','denied','expired','executed')),
    requested_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_by         TEXT,
    decided_at         TIMESTAMPTZ,
    executed_at        TIMESTAMPTZ,
    expires_at         TIMESTAMPTZ NOT NULL,
    overnight          BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX idx_approval_status ON alpha_approval_queue(status);
CREATE INDEX idx_approval_actor ON alpha_approval_queue(actor_sub);
CREATE UNIQUE INDEX idx_approval_pending_dedup
    ON alpha_approval_queue(actor_sub, parameters_hash)
    WHERE status = 'pending';

-- 2. Approval audit — immutable record of every decision
CREATE TABLE IF NOT EXISTS alpha_approval_audit (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_id     UUID REFERENCES alpha_approval_queue(id),
    action_class    TEXT[] NOT NULL,
    risk_tier       TEXT NOT NULL,
    actor_sub       TEXT NOT NULL,
    actor_type      TEXT NOT NULL,
    description     TEXT NOT NULL,
    parameters_hash TEXT NOT NULL,
    nonce           TEXT NOT NULL,
    decision        TEXT NOT NULL CHECK (decision IN ('approved','denied','expired','auto')),
    decided_by      TEXT,
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    overnight       BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX idx_audit_approval_id ON alpha_approval_audit(approval_id);
CREATE INDEX idx_audit_decided_at ON alpha_approval_audit(decided_at);

-- Immutability: app role can INSERT only — never UPDATE or DELETE
REVOKE DELETE, UPDATE ON alpha_approval_audit FROM jarvis_alpha_app;

-- 3. Overnight pre-approvals
CREATE TABLE IF NOT EXISTS alpha_overnight_approvals (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern     TEXT NOT NULL,
    max_tier    TEXT NOT NULL CHECK (max_tier IN ('T1','T2','T3')),
    budget_usd  NUMERIC(10,2),
    created_by  TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    revoked_by  TEXT
);

-- 4. Grant permissions to app role
GRANT SELECT, INSERT, UPDATE, DELETE ON alpha_approval_queue TO jarvis_alpha_app;
GRANT SELECT, INSERT ON alpha_approval_audit TO jarvis_alpha_app;
GRANT SELECT, INSERT, UPDATE ON alpha_overnight_approvals TO jarvis_alpha_app;

COMMIT;
