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
| `alpha_agent_runs` | Future run ledger for managed agent executions. |
| `alpha_agent_events` | Future event ledger for agent observability. |

## API Surface

| Route | Purpose | Tier |
|---|---|---|
| `GET /v1/skills` | List registered skills. | T2 security read |
| `GET /v1/skills/{skill_name}` | Read one skill spec. | T2 security read |
| `GET /v1/agents` | List registered agents. | T2 security read |
| `GET /v1/agents/{agent_id}` | Read one agent spec. | T2 security read |
| `POST /v1/agents/{agent_id}/enable` | Enable an agent in the registry. | T5 admin control |
| `POST /v1/agents/{agent_id}/disable` | Disable an agent in the registry. | T5 admin control |

The first registry PR does not create new long-running agents. It only creates
the contract, persistence, and guarded control surface.

## First Seed Skills

The initial seed covers foundation and near-term waves:

- `notify.send_pushover`
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
| `buddy` | active/enabled | Existing live housekeeping agent. |
| `dream_mode` | active/enabled | Existing Temporal worker path. |
| `ken_voice` | planned/disabled | First low-risk new agent candidate. Draft-only, no side effects. |
| `network_watchdog` | planned/disabled | First read-only monitoring agent candidate. |
| `inbox_watcher` | planned/disabled | Gmail read/classification path. |
| `family_concierge` | planned/disabled | Child-facing request router. |

## Next Build Recommendation

`notify.send_pushover` is active. It is a Gateway-egress skill: Brain calls
Gateway over Tailscale with `curl`; Gateway owns `PUSHOVER_USER_KEY` and
`PUSHOVER_APP_TOKEN` and calls the Pushover API. The skill is T2, mutating, and
requires an idempotency key.

After the Pushover skill PR lands, the next production slice should be:

1. Add a `network_watchdog` run loop in disabled-by-default mode.
2. Enable read-only UniFi controller data behind the registry contract.
3. Route watchdog alerts through `notify.send_pushover`.

That path gives Alpha a real new agent without making Gmail, iMessage, or child
surfaces the first test case.
