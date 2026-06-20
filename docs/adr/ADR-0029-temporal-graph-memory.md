# ADR-0029: Temporal Graph Memory

Date: 2026-06-20

Status: Proposed

Related: GitHub issue #513

Extends:

- ADR-0025 Memory 2.0 Dream Consolidation Boundary
- ADR-0026 Reviewed Consolidation Writes
- ADR-0027 Spark Target Memory Lane

## Context

Alpha now has several memory lanes:

- `alpha_semantic_memory` stores reviewed or explicit fact memory.
- `alpha_conversation_memory` stores working and episodic memory.
- `alpha_memory_consolidation_proposals` stores Dream reviewed-write proposals.
- `alpha_profile_relationships` stores admin-managed Alpha Settings profile
  relationships.
- `alpha_personality_memory` stores Spark-approved identity, voice, boundary,
  and relationship memory.

Those lanes do not model facts that change over time. Relationship, project,
role, ownership, team, and status facts need current-truth reads and historical
as-of reads without overwriting prior truth.

Examples:

- "Sweta is working on X" may later become "Sweta finished X."
- "Project Alpha is blocked by backup restore" may later become green.
- "Person A reports to Person B" can change without making the old fact false
  for old conversations.
- Child, health, legal, and identity relationships require auditability and
  review before graph traversal or writeback.

The risk is that graph memory can become an unbounded authority layer. It can
connect people, children, projects, health facts, and legal context across
principals. Silent automatic writes or broad traversal would increase privacy,
security, and correctness risk.

## Decision

Add temporal graph memory as a separate versioned lane for changing facts.

Temporal graph memory augments semantic memory. It does not replace semantic
memory, Spark memory, or admin profile relationships.

The first implementation must be reviewed, admin-visible, RLS protected, and
append-first:

- No automatic graph writes from Chat, Ask, Buddy, Spark, or Dream without a
  reviewed proposal and approved write path.
- No hard delete in the first production slice.
- No cross-principal traversal unless the caller is platform admin or a later
  ADR defines a narrower delegated read policy.
- No raw sensitive fact text in monitor alerts, logs, or dashboard summaries.
- Every mutable graph fact keeps provenance, actor, review status, confidence,
  validity window, and supersession lineage.

## Memory Lane Boundaries

| Lane | Owns | Does not own |
|---|---|---|
| Semantic memory | Stable user-visible facts and explicit `/memory` saves | Time-versioned relationship history |
| Conversation memory | Working and episodic context | Long-term current truth |
| Dream consolidation | Reviewed candidate discovery and proposal generation | Silent writes or graph traversal |
| Profile relationships | Admin Settings relationship rows between Alpha profiles | Historical versions, non-profile project/person graph facts |
| Spark personality memory | Reviewed voice, boundary, identity, and relationship cues for Spark | Queryable time-travel graph |
| Temporal graph memory | Versioned nodes/edges for changing people, projects, roles, ownership, relationships, and statuses | Raw transcript storage or unchecked inferred truth |

## Data Model Direction

The first schema should use explicit node and edge tables rather than storing
everything as JSONB blobs.

### Nodes

`alpha_memory_graph_nodes`

Required fields:

- `id uuid primary key`
- `principal_id text not null`
- `node_type text not null`
- `external_ref_type text`
- `external_ref_id text`
- `label_hash text not null`
- `label_preview text`
- `properties jsonb not null default '{}'`
- `source text not null`
- `provenance jsonb not null default '{}'`
- `confidence double precision not null`
- `review_status text not null`
- `valid_from timestamptz not null`
- `valid_to timestamptz`
- `superseded_by uuid`
- `created_by text not null`
- `reviewed_by text`
- `reviewed_at timestamptz`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

### Edges

`alpha_memory_graph_edges`

Required fields:

- `id uuid primary key`
- `principal_id text not null`
- `from_node_id uuid not null`
- `to_node_id uuid not null`
- `edge_type text not null`
- `properties jsonb not null default '{}'`
- `source text not null`
- `provenance jsonb not null default '{}'`
- `confidence double precision not null`
- `review_status text not null`
- `valid_from timestamptz not null`
- `valid_to timestamptz`
- `superseded_by uuid`
- `created_by text not null`
- `reviewed_by text`
- `reviewed_at timestamptz`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

### Audit Ledger

`alpha_memory_graph_audit`

Required fields:

- graph node or edge id
- operation
- old version id
- new version id
- approval queue id
- actor
- source surface
- reason
- created at
- rollback payload

The audit ledger is append-only. If a relationship changes, the old row gets
`valid_to` and the new row links back through supersession. Historical rows stay
queryable for as-of reads.

## Write Workflow

All graph writes use reviewed proposals and SECURITY DEFINER functions.

1. Source system emits a candidate graph change with bounded evidence.
2. Candidate is visible in Helm Manage Memory.
3. Approval Gateway creates a T5 queue item for the graph write.
4. Executor validates the Approval Gateway token and proposal binding.
5. SECDEF function sets RLS role internally.
6. Function writes the new version, closes the previous active version when
   applicable, and appends audit in one transaction.
7. Function returns only ids, counts, and status. It does not emit raw sensitive
   values to logs.

The executor must fail closed if:

- the approval token is missing, expired, mismatched, or already consumed
- the candidate source row has drifted
- the source principal boundary changed
- the edge crosses principals without platform-admin context
- a child, health, legal, or identity classification lacks explicit review

## Read APIs

Initial read APIs:

- current graph facts by principal, node type, and edge type
- historical graph facts as of timestamp
- supersession history for one node or edge
- aggregate health only for Helm strip counters

The default user-facing read should return current approved rows only.

Admin reads may include pending, rejected, archived, and historical rows, but
raw text previews should stay bounded and redacted where practical.

## RLS and Privacy

All graph tables must have RLS enabled and FORCE RLS.

Policies:

- principal-scoped rows are visible to the owning principal only where a later
  route explicitly allows user reads
- platform admin can review and operate across principals
- write policies should be admin-only in the first slice
- SECDEF functions set `rls.role` internally

Sensitive graph classes require explicit review:

- child profile facts
- health facts
- legal facts
- custody or family relationship facts
- identity and protected relationship facts
- access-control or ownership facts

Monitor outputs must be count-only:

- open graph proposals
- stale graph proposals
- graph approval mismatches
- executed graph writes without audit
- current rows by class
- last graph activity

## Performance

Indexes required in the first migration:

- active current rows by `principal_id`, `node_type`, `valid_to is null`
- active current edges by `principal_id`, `edge_type`, `valid_to is null`
- as-of lookup by `principal_id`, `valid_from`, `valid_to`
- supersession lookup by `superseded_by`
- approval and audit lookup by approval queue id

The first read API should page results and cap graph traversal depth to 1.
Multi-hop traversal is deferred until there are explicit use cases and tests.

## Rejected Alternatives

### Store temporal facts only in semantic memory

Rejected. Semantic memory can say "current known fact", but it cannot answer
"what did we believe on this date" without ad hoc parsing and overwrite risk.

### Extend `alpha_profile_relationships`

Rejected for the first graph slice. Profile relationships are an Alpha Settings
admin surface. Temporal graph memory must also represent projects, roles,
ownership, status, and non-profile entities.

### Use a graph database now

Rejected for now. Postgres keeps the RLS, backup, restore, audit, and migration
model consistent. A graph database can be reconsidered only if Postgres queries
become the bottleneck.

### Allow Dream or Buddy to write graph facts directly

Rejected. Dream and Buddy may propose graph facts, but graph writes need review,
approval provenance, and audit.

## Rollout Plan

### PR 1: ADR only

Define boundaries, schema direction, write workflow, privacy rules, and rollout.

### PR 2: Schema and rollback

Add reversible migrations for graph nodes, graph edges, and graph audit.
Rollback must fail safely if graph rows exist.

### PR 3: Reviewed write functions

Add SECDEF functions for create, supersede, archive, and revert.
Add tests for approval binding, candidate drift, RLS, FORCE RLS, and audit.

### PR 4: Read APIs

Add current and as-of read APIs with pagination and traversal depth 1.

### PR 5: Helm visibility

Show graph health, open proposals, and per-user current graph counts in Manage
Memory. Do not show raw sensitive facts by default.

## Verification Required Before Production

- Unit tests for current lookup, as-of lookup, supersession, and archive.
- Migration tests for RLS, FORCE RLS, grants, and rollback safety.
- Route classification tests for graph read and reviewed-write routes.
- Integration smoke for Helm Manage Memory graph counters.
- Restore drill after schema migration.
- Production readiness monitor includes graph proposal and audit integrity
  counts.

## Open Questions

- Whether project nodes should have a first-class project registry source or
  remain graph-only for the first slice.
- Whether user-facing graph reads should be exposed outside Helm in the first
  release.
- Whether temporal graph facts should participate in Ask grounding immediately
  or only after a separate grounding ADR.
