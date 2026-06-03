# Jarvis-Herald — Social Presence Agent (Spec)

**Module:** `jarvis-herald` · repo `kphaas/jarvis-herald`
**Glyph:** beacon ring + teal node + **a folded newspaper** (the herald carries the news)
**Purpose:** manage and **grow** your social presence across X, LinkedIn, Instagram — in your voice, behind human-approval gates.

> North Star: a presence that compounds while you stay in control. Herald watches, drafts, schedules, and surfaces opportunities. **You approve every send.** Capabilities arrive as **skills** you switch on over time.

---

## F / A / R / R

**Facts**
- Goal: social **management + growth** (presence, engagement, outreach), skill-based.
- Locked: **Buffer** publishes IG + LinkedIn; **draft + you approve every send**; **CC drafting now**, module later.
- Reuses your stack: NATS approval gates, LLMPort, Postgres+pgvector, OTel, Pushover/Mattermost, RS256 JWT.

**Assumptions**
- Drafting voice comes from `docs/brand/MESSAGING.md` + `BRAND.md`; angles from `campaign-plan.md`.
- Runs as a container on **Sandbox** (capability node), like Financial/Medical.
- Your current `/social-draft` CC prompt becomes the seed for Herald's first skill (continuity, no rework).

**Risks**
- ⚠️ **ToS / bans** — mass auto-engagement = bans. *Mitigation: no autonomous sends, ever; approval-gated; rate caps as circuit breakers.*
- ⚠️ **Brand drift** — off-voice drafts. *Mitigation: advisory voice-lint + brand-safety; you approve every send.*
- ⚠️ **API churn** — X/Meta change terms. *Mitigation: thin adapters behind ports; swap without touching core.*
- ⚠️ **LLM cost creep** — drafting spend. *Mitigation: hard monthly cap as circuit breaker (policy.py).*

**Recommendation**
Skill-based module, **8 phases**, drafting first (mirrors what you do today), publishing via Buffer next, engagement + outreach last — each gated. Build only when manual drafting feels slow.

---

## Scope

**In:** presence tracking (read-only), AI drafting in voice → approval → schedule → publish (Buffer/X), engagement inbox (draft replies → approve), outreach tracking + drafts, weekly metrics digest, Alpha dashboard API.

**Out (by design):** 🚫 autonomous posting/replying/liking/following · 🚫 mass/auto-engagement, bulk DMs · 🚫 scraping behind logins · 🚫 storing others' PII beyond public handles + public text.

---

## Architecture — skill-based, hexagonal

Monolith per capability module. A small **core runtime** + a **registry of Skills**. Core knows nothing about X/Buffer/Anthropic — only ports.

### Core runtime
Orchestrator · Skill registry · Approval gate (NATS) · Scheduler · Policy engine (`policy.py`) · DAL · Observability. Default deny: anything not allowed by policy doesn't run.

### Skills (the part you grow over time)
Each skill is a plug-in behind one contract. **Add a skill = one file + one entry in `config/skills.yaml`; CI runs its checks. Remove = `enabled: false`. Zero core changes.**

```python
# core/ports/skill.py
class SkillPort(Protocol):
    name: str
    version: str
    capability: Literal["draft","schedule","publish","listen","reply","outreach","track","digest"]
    approval_tier: int                  # from policy.py; 0 = no send
    async def run(self, ctx: SkillContext) -> SkillResult: ...
    async def health_check(self) -> HealthStatus: ...
```

| Skill | Does | Sends? |
|---|---|---|
| `draft` | generate posts in your voice (LLMPort) — your `/social-draft` prompt, productized | no |
| `voice_lint` | advisory: drafts vs BRAND.md voice rules → score + notes | no |
| `brand_safety` | advisory: flag off-brand / over-promising / risky copy | no |
| `track` | ingest post + account metrics → snapshots | no |
| `schedule` | queue + time approved posts | no |
| `publish` | push **approved** posts (Manual → Buffer → X adapters) | **gated** |
| `listen` | pull mentions / replies / comments | no |
| `reply` | draft engagement responses (advisory) → approval | **gated** |
| `outreach` | find + track target accounts, draft outreach | **gated** |
| `digest` | weekly summary → Pushover / Mattermost | no |

### Ports + adapters (infrastructure)

| Port | Adapters |
|---|---|
| `PublisherPort` | `ManualAdapter` (safest first) → `BufferAdapter` (IG+LinkedIn+X) → `XAdapter` |
| `InboxPort` | `XAdapter`, `BufferAdapter` (where available) |
| `MetricsPort` | `XAdapter`, `BufferAdapter` |
| `LLMPort` | `Anthropic` / `OpenAI` / `Ollama` (swap via config) |
| `ApprovalPort` | `NatsApprovalAdapter` (reuse buddy-agent / task-graph approval) |
| `NotifyPort` | `Pushover` / `Mattermost` |
| `Dal` | `AsyncpgDal` (raw SQL migrations) |

Advisory-only: `voice_lint` / `brand_safety` never block — they annotate; you decide.

---

## Data model (Herald-owned schema)

```
accounts(platform, handle, type, tokens_ref, active)
skills(name, version, capability, enabled, config)          -- the registry
skill_runs(skill, started, cost_usd, outcome, tokens)       -- per-run telemetry (Forge-style)
campaigns(name, goal, channel_set, start, end, status)
posts(campaign_id, body, media_refs, angle, status)
drafts(post_id, llm_model, voice_score, safety_flags, version)
scheduled_posts(post_id, account_id, scheduled_at, publish_state)
mentions(account_id, platform, external_id, author, text, ts, handled)
engagement_actions(mention_id, kind, draft_text, approval_id, sent_at)
outreach_targets(handle, platform, why, stage, last_touch)
metric_snapshots(scope_id, metric, value, captured_at)
approval_requests(subject, payload, tier, state, decided_by, decided_at)
audit_log(actor, action, entity, before, after, ts)
```

API mandate: Herald owns this data. Alpha reads via **typed API only** (never DB-to-DB).

---

## Safety & guardrails (defense-in-depth)

1. **Human-approval gate on every outbound action** (publish / reply / outreach) via `ApprovalPort` → approve by Pushover/Mattermost tap. Default deny.
2. **One `policy.py`** = single source of truth for approval tiers + rate caps + cost cap. No tier logic scattered.
3. **Rate caps = circuit breakers** (posts/day, replies/hour per platform). Trip → pause + notify.
4. **ToS guard** — autonomous engagement is structurally impossible; the only path to "send" is an approved request.
5. **Monthly LLM cost cap** — hard cutoff (your Council ADR-0003 pattern).
6. **Audit everything**; secrets in `~/jarvis/.secrets` (chmod 600), redacted in logs.

---

## Infra / placement

- **Node:** Sandbox (`jarvis-sandbox`), Docker + Portainer
- **DB:** Herald Postgres schema (own volume); pgvector for draft similarity / "don't repeat yourself"
- **NATS:** add a **`HERALD`** account (isolation, like ALPHA/FINANCIAL/FAMILY/MEDICAL)
- **Cache/queue:** Redis (scheduling, rate-limit counters)
- **Observability:** OTel traces + metrics, structured JSON logs, Grafana/Prometheus
- **Dev path:** `uv run` dev, Docker prod

---

## Phases (spec-in → overnight execution → approve at gates)

| # | Phase | Delivers | Gate |
|---|---|---|---|
| **P0** | Foundations | repo + hexagonal skeleton, **SkillPort + registry**, domain models, DAL migration, config, secrets, OTel, CI (ruff+bandit+pytest) | Council 4-lens |
| **P1** | `draft` skill | LLMPort drafting in voice (seed = your `/social-draft`), `voice_lint` + `brand_safety` advisory, ApprovalPort wired | Council |
| **P2** | `track` skill | MetricsPort + adapters, snapshots, content-calendar | Human approve |
| **P3** | `schedule` + `publish` | Manual → Buffer → X; approval-gated; rate caps | **Cyber** (ToS/secrets) |
| **P4** | `listen` + `reply` | InboxPort + adapters, advisory reply drafts, approval flow, no-auto-engage guard | Council 4-lens |
| **P5** | `outreach` skill | target tracking, opportunity suggestions (advisory), draft outreach → approval | Human approve |
| **P6** | `digest` + Alpha API | weekly digest (Pushover/Mattermost), typed API for dashboard | Human approve |
| **P7** | Hardening | property tests, DR runbooks, cost-cap proof, final review | Council 4-lens |

**Council 4-lens** = CIO / Cyber / EA / Jobs (advisory). **CI owns enforcement** so drift is blocked even if Forge is bypassed.

---

## ADR-0016 — Herald social module

- **Context:** managed social growth without ToS risk or brand drift.
- **Decision:** skill-based capability module, hexagonal; Buffer + X publishing; **all outbound actions human-approved via NATS**; skills toggled via config; autonomous engagement out of scope.
- **Consequences:** slower than full automation, but ban-safe, on-voice, auditable, and extensible one skill at a time.

---

## Brand

- Marks: `herald-color.svg`, `-animated.svg` (newspaper + sonar ping), `-mono.svg`, `-favicon.svg`, `-appicon.png`, `-social.png`
- Location: `docs/brand/sub-products/herald/`
- One-liner: *"Manage + grow your social, in your voice."*

---

## Decisions (locked)

| # | Decision | Choice |
|---|---|---|
| D1 | Drafting model | **Anthropic API** (best voice for public copy) — Ollama as configurable fallback |
| D2 | Metrics source (`track`) | **Buffer analytics** (one source, low friction) |
| D3 | Monthly LLM cost cap | **$15/mo** hard cap (circuit breaker in `policy.py`) |
| D4 | Outreach posture (P5) | **Suggest + draft only** — you pick who to engage |
| D5 | Skill granularity | **One skill per capability** (toggle each in `config/skills.yaml`) |

---

## Pre-flight (when you drop to Forge)

1. Add `HERALD` NATS account + service token (RS256 JWT)
2. Add secrets to `~/jarvis/.secrets`: Buffer token, X API keys, LLM keys
3. `gh repo create kphaas/jarvis-herald --private`
4. Drop spec to `~/jarvis-forge/inbox/jarvis-herald/`
5. Forge runs P0 → opens PR → review at the Council gate
