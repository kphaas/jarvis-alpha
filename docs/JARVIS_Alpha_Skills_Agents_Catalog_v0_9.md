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
| `inbox_watcher` | planned/disabled | Gmail read/classification path. |
| `family_concierge` | planned/disabled | Child-facing request router. |

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

## Next Build Recommendation

After the AgentEvent and Mattermost command slice lands, the next production
slice should be:

1. Complete the 24-hour soak review for `chatops_smoke` and the disabled
   `network_watchdog` posture.
2. If soak is clean, enable `network_watchdog` and watch notification noise for
   one day.
3. Start Gmail read-only only after the encrypted body vault, redaction helper,
   and VIP-group fail-closed contract are deployed.

That path gives Alpha a real new agent without making Gmail, iMessage, or child
surfaces the first test case.
