# Temporal POC Plan — Evening Prototype

**Date:** 2026-04-10
**Goal:** Determine in 2-4 hours whether Temporal is the right replacement for TaskGraphExecutor in Alpha-2.
**Trigger:** Stage 5d discovery surfaced that the entire R1/R2/TD-44 bug class is solved out-of-the-box by Temporal. Worth a structured POC before committing to fix or replace.

---

## Decision Criteria

After POC, Temporal is GO if all of these hold:
- ✅ Workflow definition feels natural in Python
- ✅ Postgres backend works on Brain without container weirdness
- ✅ Retry/timeout/approval semantics map cleanly to existing JARVIS patterns
- ✅ Observability (Temporal Web UI) is genuinely useful

Temporal is NO-GO if any of these:
- ❌ SDK fights you on basic patterns
- ❌ Backend setup needs Docker or major rework
- ❌ Auth model can't accommodate JWT/PIN
- ❌ Operational overhead exceeds value

---

## Pre-Work (15 min)
- Read Temporal Python SDK quickstart: https://docs.temporal.io/develop/python
- Skim "Workflows vs Activities" mental model
- Skim "Signals and Queries" (needed for approval gateway pattern)

## Phase 1 — Install Temporal Server on Brain (30 min)

▶ BRAIN —
brew install temporal

▶ BRAIN —
temporal server start-dev --db-filename ~/jarvis/temporal-poc.db --ui-port 8233

UI at http://localhost:8233.

Fallback if Homebrew fails:
curl -sSf https://temporal.download/cli.sh | sh

## Phase 2 — Hello Workflow (30 min)

In a scratch dir on Air (NOT in jarvis-alpha repo):
mkdir -p ~/temporal-poc && cd ~/temporal-poc
python3.12 -m venv .venv && source .venv/bin/activate
pip install temporalio

Build smallest possible workflow:
- One workflow that calls one activity
- Activity sleeps 2 seconds and returns a string
- Worker runs locally, hits Brain's Temporal server via Tailscale

If this works in 30 min, Temporal is viable.

## Phase 3 — JARVIS-Shaped Workflow (60 min)

Build a workflow that mirrors what TaskGraphExecutor does today:

```python
@workflow.defn
class TaskGraphWorkflow:
    @workflow.run
    async def run(self, graph_request: GraphRequest) -> GraphResult:
        plan = await workflow.execute_activity(
            llm_plan, graph_request,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=3)
        )

        if plan.requires_approval:
            await workflow.wait_condition(lambda: self._approved is not None)
            if not self._approved:
                return GraphResult(status="cancelled")

        results = await asyncio.gather(*[
            workflow.execute_activity(run_step, step)
            for step in plan.steps
        ])

        return GraphResult(status="completed", results=results)

    @workflow.signal
    def approve(self, decision: bool):
        self._approved = decision
```

**Honest test:** does this feel better than `TaskGraphExecutor`?

## Phase 4 — The Hard Questions (30 min)

Answer before go/no-go decision:

1. **Authentication.** Can Temporal use JWT/PIN auth, or does it want its own? (Custom auth interceptors supported.)
2. **Backend.** Postgres backend exists. Migration from `start-dev` SQLite to Brain Postgres = ~30 min config change.
3. **Cost gating.** Activities are pure functions — wrap with existing `get_secret() + cost tracker` pattern? (Yes, decorators work.)
4. **Child profile policy.** Inject content tier checks at activity boundary. Same pattern as today.
5. **Observability.** Does Temporal Web UI integrate with Loki/Grafana?
6. **Lock-in.** Open source MIT, runs on your hardware. Lower lock-in than building your own.

## Decision Matrix

| Criterion | Weight | Temporal | Hand-rolled (current) |
|---|---|---|---|
| Time to ship Alpha-2 TaskGraph | High | -1 (learning curve) | +1 (existing code) |
| Bug class elimination (R1/R2/TD-44) | High | +3 | -1 (recurring) |
| Long-term maintenance | High | +2 (battle-tested) | -2 (you maintain) |
| Observability | Medium | +2 (Web UI built in) | 0 |
| Operational complexity | Medium | -1 (extra service) | +1 |
| Solo-operator friendliness | High | 0 | 0 |

Tentative score: Temporal +5, hand-rolled -2. Real number depends on POC feel.

## Go/No-Go Output

After ~3 hours, write `~/jarvis-alpha/docs/TEMPORAL_DECISION.md`:
- ✅ What worked
- ❌ What didn't
- 🤔 What surprised
- **Decision:** Adopt for Alpha-2 / Defer 6 months / Reject

If **Adopt** → TaskGraphExecutor gets deletion ticket, Alpha-2 plans rewrite, TD-53 closes as wontfix.
If **Defer/Reject** → R2 fix happens in next session, TD-53 becomes P1.

---

## What This POC Does NOT Decide

- Whether to keep RLS (separate question — Temporal doesn't replace RLS)
- Whether to adopt OPA/Cedar (separate question — child profile policy)
- Whether to migrate to Postgres-as-message-bus patterns (separate)

POC scope is strictly: **does Temporal replace TaskGraphExecutor for Alpha-2?**
