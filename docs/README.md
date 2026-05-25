# JARVIS Alpha — Documentation Index

**April 2026 · github.com/kphaas/jarvis-alpha · main**

Single entry point for all jarvis-alpha documentation. Each doc owns one concern.
Update its dedicated file — never duplicate content across docs.

---

## By Concern

### Architecture & Roadmap
- [`JARVIS_Alpha_Architecture_Review_V2.md`](./JARVIS_Alpha_Architecture_Review_V2.md) — Canonical system overview, node topology, services, and Alpha-5 deployment model
- [`JARVIS_Alpha_Phase_Status.md`](./JARVIS_Alpha_Phase_Status.md) — Historical phase tracker with April 18 addendum; use Architecture Review V2 for current roadmap
- [`ALPHA5_MIGRATION_PLAN.md`](./ALPHA5_MIGRATION_PLAN.md) — Approved Alpha-5 state-native / compute-containerized migration plan

### Backend Standards
- [`PATTERNS.md`](./PATTERNS.md) — Backend coding patterns (asyncpg, curl, logging)
- [`SERVICE_CONTRACTS.md`](./SERVICE_CONTRACTS.md) — Inter-service API contracts
- [`DB_CONTRACTS.md`](./DB_CONTRACTS.md) — Postgres schema contracts and invariants
- [`MIDDLEWARE_STACK.md`](./MIDDLEWARE_STACK.md) — Request lifecycle, middleware order, JSONB encoding, scope enforcement

### Security & Identity
- [`SERVICE_IDENTITY_MODEL.md`](./SERVICE_IDENTITY_MODEL.md) — RS256 JWT, multi-key validation, scope registry, key rotation
- [`APPROVAL_GATEWAY_SPEC.md`](./APPROVAL_GATEWAY_SPEC.md) — Risk tiers (T1-T5), approval queuing, audit
- [`RLS_ROLLOUT_PLAN.md`](./RLS_ROLLOUT_PLAN.md) — Row-level security migration plan

### Frontend Standards
- [`ALPHA_UI_STANDARDS.md`](./ALPHA_UI_STANDARDS.md) — React 19, Tailwind, React Query, hooks, components, patterns

### Subsystem Specs
- [`DREAM_MODE_SPEC.md`](./DREAM_MODE_SPEC.md) — Overnight agent execution model

### Session History
- [`handoffs/`](./handoffs/) — Per-session handoff notes (one file per session)

---

## By Audience

### New Developer Onboarding
1. Start with [`JARVIS_Alpha_Architecture_Review_V2.md`](./JARVIS_Alpha_Architecture_Review_V2.md) — understand the system
2. Read [`PATTERNS.md`](./PATTERNS.md) — learn the coding conventions
3. Skim [`MIDDLEWARE_STACK.md`](./MIDDLEWARE_STACK.md) — understand request lifecycle
4. Bookmark [`ALPHA_UI_STANDARDS.md`](./ALPHA_UI_STANDARDS.md) if working on frontend

### Adding a New Backend Route
1. [`MIDDLEWARE_STACK.md`](./MIDDLEWARE_STACK.md) — section 5 (scope enforcement pattern)
2. [`SERVICE_IDENTITY_MODEL.md`](./SERVICE_IDENTITY_MODEL.md) — pick or define a scope
3. [`PATTERNS.md`](./PATTERNS.md) — asyncpg + JSONB + curl patterns
4. [`DB_CONTRACTS.md`](./DB_CONTRACTS.md) — if adding a new table
5. [`APPROVAL_GATEWAY_SPEC.md`](./APPROVAL_GATEWAY_SPEC.md) — classify the route's risk tier

### Adding a New Frontend Page or Component
1. [`ALPHA_UI_STANDARDS.md`](./ALPHA_UI_STANDARDS.md) — full conventions doc
2. Existing components in `~/jarvis-alpha/ui/src/components/<page>/` for reference
3. Existing hooks in `~/jarvis-alpha/ui/src/hooks/` for the React Query pattern

### Security Review
1. [`SERVICE_IDENTITY_MODEL.md`](./SERVICE_IDENTITY_MODEL.md) — auth model
2. [`MIDDLEWARE_STACK.md`](./MIDDLEWARE_STACK.md) — enforcement layers
3. [`APPROVAL_GATEWAY_SPEC.md`](./APPROVAL_GATEWAY_SPEC.md) — high-risk action gating
4. [`RLS_ROLLOUT_PLAN.md`](./RLS_ROLLOUT_PLAN.md) — data isolation status

### Deploying or Operating
1. [`JARVIS_Alpha_Architecture_Review_V2.md`](./JARVIS_Alpha_Architecture_Review_V2.md) — section on commit/deploy workflow
2. Latest [`handoffs/`](./handoffs/) entry — current operational state

### Superseded
- [`archive/JARVIS_Alpha_Architecture_Review_V1.md`](./archive/JARVIS_Alpha_Architecture_Review_V1.md) — archived historical review; superseded by V2 and ADR-0002

---

## Documentation Rules

These docs are treated as a system, not a dumping ground:

1. **One concern per doc.** If something doesn't fit any existing doc, create a new one — don't pollute an unrelated doc.
2. **Never duplicate content.** Link from one doc to another instead of copy-pasting.
3. **Update on commit.** When code changes a documented pattern, update the doc in the same commit.
4. **Date the doc.** Header includes month/year of last meaningful update.
5. **Mark anti-patterns.** Each standards doc should have a "DO NOT" section.
6. **No stale specs.** If a spec is superseded, mark it deprecated at the top — don't silently leave it.

---

*README.md · April 2026 · github.com/kphaas/jarvis-alpha*
