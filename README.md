# jarvis-alpha

Private AI agent platform. Successor to jarvis-core.

## Node Topology

| Node | Machine | IP | Port | User | Role |
|---|---|---|---|---|---|
| Brain | Mac Studio M2 Ultra | via node_addresses.py | 8183 | jarvisbrain | Orchestrator, Postgres, Ollama, Buddy |
| Gateway | Mac Mini | via node_addresses.py | 8283 | infranet | Internet egress, LLM proxy, MCP |
| Endpoint | Mac Mini M1 | via node_addresses.py | 4100 | jarvisendpoint | Dashboard, Voice, nginx |
| Sandbox | Mac Mini M1 | via node_addresses.py | 5001 | jarvissand | jarvis-forge dev pipeline |

## Repos
- github.com/kphaas/jarvis-alpha — this repo
- github.com/kphaas/jarvis-core — production system
- github.com/kphaas/jarvis-forge — AI dev pipeline

## Phase Status
- Alpha-0: Paper design + schema — IN PROGRESS
- Alpha-1: Brain skeleton + TaskGraph — PLANNED
- Alpha-2: Gateway + Buddy — PLANNED
- Alpha-3: Endpoint + UI — PLANNED
- Alpha-4: Cut over from jarvis-core — PLANNED
