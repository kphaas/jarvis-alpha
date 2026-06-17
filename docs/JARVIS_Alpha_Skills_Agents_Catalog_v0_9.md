# JARVIS Alpha Skills and Agents Catalog

Status: v0.9 review candidate  
Date: 2026-05-25  
Owner: Ken Haas

This document is the working contract for Alpha's next expansion: skills are
callable functions, agents are managed loops, and every domain follows the same
shape:

`port -> adapter -> skill -> agent`

## Locked Corrections

| Topic | Decision |
|---|---|
| Document version | v0.9 review candidate until first registry PR deploys and the full catalog is reconciled. |
| BlueBubbles host | Endpoint M4 24GB for now. A macOS VM on Unraid can be investigated, but iMessage reliability makes a real Mac the safer production host. |
| VIP store | `~/jarvis/.secrets/vip_groups.enc` is canonical. It stores canonical contacts and per-group policies. |
| Smart home scenes | `smarthome.run_trusted_scene` is T1. Unknown scenes and direct device commands start at T4. Unlock and alarm disarm are T5. |
| Outbound non-VIP messages | Non-VIP Gmail/iMessage send is T4. T5 is reserved for detected legal, financial, security-sensitive, or child-profile attempts. |
| Meagan policy | T2 draft-only. Co-parent messages are composed by Alpha and reviewed by Ken before sending. |

## Registry Foundation

The first implementation slice creates the control plane before new agents run:

| Table | Purpose |
|---|---|
| `alpha_skill_registry` | Durable catalog of callable skills, scopes, approval tier, mutability, body access, and idempotency requirements. |
| `alpha_agents` | Durable catalog of managed agents, risk tier, enabled state, allowed skills/scopes, launch label, cost cap, and policy metadata. |
| `alpha_agent_runs` | Run ledger for managed agent executions. |
| `alpha_agent_events` | Durable event ledger for agent observability, notification delivery status, and Mattermost routing. |

## Skill Manifest v1

Every skill row carries a typed manifest under `metadata.manifest`. The manifest
is the production governance contract for skills: it gives the UI, policy gate,
tests, and future MCP tooling the same facts.

| Field | Purpose |
|---|---|
| `data_classification` | `none`, `ops`, `personal`, `message_body`, `child`, `financial`, `medical`, or `security`. Body-handling skills must be `message_body`. |
| `side_effect_class` | `read`, `write`, `external_send`, `physical_world`, `operator_notification`, or `control_plane`. Mutating skills cannot be `read`. |
| `runtime` | Timeout, retry policy, and rate-limit contract. |
| `cost` | Cost mode and max per call. Cloud-backed skills must declare their model/cost posture before activation. |
| `egress` | `none`, `local`, `gateway`, or `tailscale`, plus provider label. No URLs or secrets live here. |
| `audit` | Event name and fields to redact before logs, Mattermost, or future agent traces. |
| `compensation` | Named rollback/follow-up posture for side-effecting skills. |
| `test_ref` / `runbook_ref` | Verification and operator documentation pointers. |

The database enforces the manifest shape with
`alpha_skill_registry_manifest_v1_check`. The Python catalog validates the same
shape through `SkillManifestV1`, so drift is caught before deploy and at the DB
boundary.

## API Surface

| Route | Purpose | Tier |
|---|---|---|
| `GET /v1/skills` | List registered skills. | T2 security read |
| `GET /v1/skills/{skill_name}` | Read one skill spec. | T2 security read |
| `GET /v1/agents` | List registered agents. | T2 security read |
| `GET /v1/agents/status` | List agent health, last run, and last event summary. | T2 security read |
| `GET /v1/agents/{agent_id}` | Read one agent spec. | T2 security read |
| `GET /v1/agents/{agent_id}/events` | Read recent durable AgentEvents. | T2 security read |
| `GET /v1/agents/{agent_id}/runs` | Read recent agent run ledger rows. | T2 security read |
| `POST /v1/agents/{agent_id}/enable` | Enable an agent in the registry. | T5 admin control |
| `POST /v1/agents/{agent_id}/disable` | Disable an agent in the registry. | T5 admin control |
| `POST /v1/agents/{agent_id}/run` | Manually trigger an explicitly opted-in T1/T2 agent. | T5 admin control |
| `POST /v1/chatops/mattermost/command` | Token-authenticated read-only Mattermost slash command endpoint. | T2 security read |

The registry does not make Mattermost the internal coordination bus. Agents
persist AgentEvents first, then optionally notify the operator surface.

## First Seed Skills

The initial seed covers foundation and near-term waves:

- `notify.send`
- `notify.send_mattermost`
- `notify.send_pushover`
- `approval.canary_t4`
- `chatops.command_read`
- `unifi.wan_status`
- `unifi.clients`
- `unifi.health_check`
- `unifi.daughters_screentime`
- `gmail.search_threads`
- `gmail.read_thread`
- `gmail.draft_reply`
- `gmail.send`
- `gmail.send_vip`
- `imessage.read`
- `imessage.send`
- `imessage.send_vip`
- `smarthome.run_trusted_scene`
- `smarthome.run_scene`
- `smarthome.set_device`
- `smarthome.unlock`
- `smarthome.alarm_disarm`
- `tasks.create`
- `notes.search`

## Four-Lens Notes

| Lens | Choice |
|---|---|
| CIO | Registry first creates a durable control plane before adding new autonomous loops. |
| Enterprise Architect | Ports, adapters, skills, and agents stay separable; provider choices do not leak into agent policy. |
| AI Solo Developer | Planned agents default disabled, so each wave can ship in small reversible slices. |
| Code Production | Mutating skills carry explicit idempotency flags, body-access flags, scopes, and approval tiers. |

## Handler Coverage Guard

Active SkillRunner skills must have a concrete handler, and concrete handlers
must exist in the registry. The focused guard lives in
`brain/registry/drift.py`, with a runnable check at
`scripts/check_skill_registry_coverage.py` and pytest coverage in
`tests/test_skill_handler_coverage.py`.

The guard also blocks accidental activation of T4/T5 skills unless the skill
metadata explicitly declares `approval_queue_bridge = enabled`. High-risk skills
must stay `planned` or `disabled` until their handler is present, bridge-tested,
and marked with that metadata.

## Messaging Privacy Rail

Wave 0 creates the storage boundary before Gmail or iMessage write paths are
active:

| Item | State | Boundary |
|---|---|---|
| `brain/privacy/redaction.py` | Active helper | Message-body-like fields become deterministic hashes before logs or ChatOps payloads. |
| `brain/privacy/vip_groups.py` | Active contract | `vip_groups.enc` loading is fail-closed until a decryptor and a chmod-600 encrypted file are configured. |
| `alpha_message_body_vault` | DB foundation | Gmail/iMessage bodies are pgcrypto-encrypted, FORCE-RLS protected, and retention-bound. |
| Decrypt/read function | Not present | No body retrieval function ships in Wave 0; future reads need explicit `*.body.read` scope and PIN-gated audit. |

## Runtime Policy Gate

Agents must not call adapters directly. The required runtime path is:

`agent -> SkillRunner -> SkillPolicyGate -> approval/cost/body/idempotency checks -> adapter`

`SkillRunner` owns the handler registry and is the only intended path to invoke
a concrete provider adapter. The gate reads `alpha_agents`,
`alpha_skill_registry`, and `alpha_agent_runs` before execution. It returns one
of three outcomes:

| Outcome | Meaning |
|---|---|
| `allow` | The agent may invoke the skill adapter. |
| `approval_required` | The skill is T4/T5 and must route through the approval queue first. |
| `deny` | The call violates registry policy and must not execute. |

The first enforced checks are:

- agent exists, is `active`, and is `enabled`
- skill exists and is `active`
- skill is listed in the agent's `allowed_skills`
- skill scope is listed in the agent's `allowed_scopes`
- body reads require the derived body scope, such as `email.body.read`
- mutating idempotent skills require an idempotency key
- estimated cost must fit inside the agent's daily cap
- T4/T5 skills require an approval grant before execution

Route-level T4/T5 approvals are already handled by the Alpha Approvals tab
through `alpha_approval_queue`, `brain/middleware/approval.py`, and
`brain/routes/approvals.py`. Agent skill calls use
`brain/skills/approval_bridge.py`: first call queues a deterministic approval
item, Ken approves or denies it in the existing Approvals tab, and the agent must
retry the exact same skill call before SkillRunner consumes the approved row and
executes with `approval_granted=True`.

MCP comes later as a transport adapter over this gate:

`MCP tool -> Alpha MCP server -> SkillRunner -> SkillPolicyGate -> adapter`

MCP must never call provider adapters directly.

## First Seed Agents

| Agent | State | Note |
|---|---|---|
| `buddy` | active/enabled | Existing live housekeeping agent. Allowed to notify through Mattermost primary and Pushover fallback. |
| `dream_mode` | active/enabled | Existing Temporal worker path. Emits start, approval, kill, and final-state AgentEvents. |
| `approval_triage` | active/enabled | Approval queue events routed to `needs-input`. |
| `watchdog` | active/enabled | Infrastructure health events routed to `alerts`. |
| `ken_voice` | planned/disabled | First low-risk new agent candidate. Draft-only, no side effects. |
| `chatops_smoke` | active/enabled | Scheduled and manual notification-path smoke agent. |
| `network_watchdog` | active/disabled | First read-only monitoring agent candidate. Manual run is gated by T5 and stays disabled until soak review. |
| `approval_canary` | active/disabled | No-op T4 canary for approve/retry/consume proof. Not manually runnable. |
| `inbox_watcher` | planned/disabled | Gmail read/classification path. |
| `family_concierge` | planned/disabled | Child-facing request router. |

### Dream Mode Agent Ledger

Dream Mode remains a Temporal workflow, but it is also an Alpha agent for
governance. Final cleanup calls `upsert_dream_agent_run(session_id)`, which
mirrors `alpha_dream_sessions` into `alpha_agent_runs` using
`agent_id = 'dream_mode'`. The bridge is a `SECURITY DEFINER` function with
internal `rls.role = platform_admin`, so the Agents UI can show Dream history
without teaching every route how to join Dream-specific tables.

Backfilled rows include session ID, workflow IDs, trigger, goal type, reviewer
verdict, step counts, final status, cost, and briefing publication status.

## Notification Surface

Mattermost is the primary Alpha ChatOps surface. Agents should call
`notify.send`, not a provider-specific adapter. The provider-neutral skill sends
to Mattermost through Gateway and can fall back to Pushover when ChatOps is
unavailable. Phase 1 uses Mattermost incoming webhooks; bot-token REST remains
available for Phase 2+ slash-command follow-ups and threaded API automation.

| Skill | Role | Provider | Notes |
|---|---|---|---|
| `notify.send` | Stable agent contract | Mattermost webhook primary, Pushover fallback | T2, mutating, idempotency required. |
| `notify.send_mattermost` | Direct ChatOps send | Mattermost incoming webhook | Gateway owns `MATTERMOST_WEBHOOK_URL_ALPHA_EVENTS`; bot REST is Phase 2+. |
| `notify.send_pushover` | Wake-up fallback | Pushover | Gateway owns `PUSHOVER_USER_KEY` and `PUSHOVER_APP_TOKEN`. |

Mattermost channel routing uses the four initial ops channels:
`alpha-events`, `forge-events`, `needs-input`, and `alerts`. The Alpha Gateway
uses `MATTERMOST_WEBHOOK_URL_ALPHA_EVENTS` for routine posts and payload-level
channel override for `needs-input` and `alerts`. Optional
`MATTERMOST_CHANNEL_<KEY>_NAME` secrets can override channel names; bot REST
mode still supports `MATTERMOST_CHANNEL_<KEY>_ID` for later phases.

The first Mattermost command surface is read-only. Configure one slash command,
for example `/alpha`, to post to `/v1/chatops/mattermost/command` with the
shared `MATTERMOST_COMMAND_TOKEN` on Brain. Supported commands are `health`,
`agents`, `network`, `approvals`, and `dreams [n]`. No Mattermost route can
approve, kill, deploy, change caps, or mutate Alpha state in v0.9. Network
output is summary-only and must not print raw MACs, IPs, or client payloads.

## Obsidian Notes And Tasks

The first non-notification Dream skills are now local-only Obsidian handlers:

| Skill | State | Approval | Handler |
|---|---|---|---|
| `notes.search` | active | T1 | Searches markdown notes under `OBSIDIAN_VAULT_PATH`, skipping hidden and tool directories. |
| `tasks.create` | active | T2 | Appends an Obsidian Tasks checkbox with a required idempotency marker. |

Production configuration uses `OBSIDIAN_VAULT_PATH`; `tasks.create` optionally
uses `OBSIDIAN_TASKS_INBOX` and otherwise defaults to `Inbox.md`. Paths are
vault-relative only: absolute paths, hidden paths, traversal, and non-markdown
targets are rejected.

## Weather

`weather.current` is the first governed real-world read skill for child-facing
and operator-facing assistants. It is active, T1, read-only, and must execute
through SkillRunner. Brain never calls the public weather API directly: the
handler calls Alpha Gateway, and Gateway calls the curated `open-meteo`
registry source with a 10-minute cache. Gateway uses configured home
coordinates by default, or explicit latitude/longitude when a caller provides
both.

| Skill | State | Approval | Provider | Guardrail |
|---|---|---|---|---|
| `weather.current` | active | T1 | Open-Meteo (`open-meteo`) via Gateway | No address geocoding, no broad web/search access, cache TTL 600s. |

## Approval Canary

`approval.canary_t4` is a no-op T4 skill with
`approval_queue_bridge = enabled`. It exists to prove the SkillRunner approval
path before real high-risk skills are activated:

`agent call -> approval queue -> Approvals tab decision -> same call retry -> handler executes -> queue row consumed`

The paired `approval_canary` agent is `active` but `enabled = false`, has no
manual runner, and has no external side effects. It is not a product feature;
it is a production safety test hook.

## Next Build Recommendation

After the registry drift guard, Obsidian seed handlers, SkillRunner approval
bridge, and inactive approval canary land, the next production slices should be:

1. If Dream 48-hour soak stays clean, promote Dream Mode from soak to production
   accepted and keep ledger mirroring as the operator history.
2. Start Gmail read-only only after the encrypted body vault, redaction helper,
   and VIP-group fail-closed contract are deployed.
3. Then begin inbox classification with read-only, redacted summaries before
   any email write paths are activated.
4. Design the child avatar/tablet surface as a request client of Alpha, not as
   an autonomous agent with independent privileges.

That path gives Alpha a real new agent without making Gmail, iMessage, or child
surfaces the first test case.
