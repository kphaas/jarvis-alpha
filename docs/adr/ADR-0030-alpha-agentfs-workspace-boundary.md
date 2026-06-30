# ADR-0030: Alpha AgentFS Workspace Boundary

Date: 2026-06-30

Status: Proposed

Related: Alpha AgentFS MVP

## Context

Prompt and chat history are good for hot context, not large working files.
Alpha also needs a governed place for per-run artifacts without turning
Postgres into a blob store or silently promoting files into shared memory.

## Decision

Phase 1 adds a per-run local workspace under an Alpha-owned root.

- `alpha_agent_runs` keeps workspace governance metadata.
- Workspace file contents live on disk under that run root.
- Artifact metadata is append-only in both `artifacts.jsonl` and
  `alpha_agent_run_artifacts`.
- Alpha remains the source of truth for run existence, auth, approvals, audit,
  and any future promotion path.

## Boundaries

- Prompt/history is not the artifact store.
- Workspace is working context, not durable shared memory.
- Durable memory, approvals, and any external action still require explicit
  Alpha APIs and existing review gates.
- Phase 1 is `LocalWorkspaceBackend` only. No distributed filesystem, cross-run
  search, memory promotion rewrite, or direct file-serving endpoint.

## Consequences

- Large artifacts stay out of Postgres bodies.
- Future backends can replace the local implementation behind the same control
  plane contract.
- Operator surfaces can inspect governed metadata without widening write scope
  or bypassing approval boundaries.
