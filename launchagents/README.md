# launchagents/

Canonical location for all JARVIS-alpha LaunchAgent plist files.

## Why flat (no subdirectories)

This directory mirrors the runtime layout on each node (`~/Library/LaunchAgents/`). launchd only scans flat directories — subdirectories would not be loaded at runtime. Matching the runtime shape eliminates deploy-time transformation and makes a single `ls` the source of truth.

## Naming convention

Target form: `com.jarvis.alpha.<category>.<name>.plist`

Category prefixes in use:

| Prefix | Purpose | Examples |
|---|---|---|
| `service` | Core runtime services | `com.jarvis.alpha.service.brain` (target) |
| `rotate` | Scheduled token/key rotation | `com.jarvis.alpha.rotate.brain_service` |
| `sweep` | Sweep-owned security checks/remediation | `com.jarvis.alpha.sweep-cert-renewal.brain` |
| `power` | Telemetry — hardware power sampling | `com.jarvis.alpha.power.brain` |
| `observability` | Log shipping / aggregation | `com.jarvis.alpha.fluentbit`, `com.jarvis.alpha.loki` (target rename: `observability.fluentbit` / `observability.loki`) |

**Legacy labels** (without category prefix): `com.jarvis.alpha.brain`, `com.jarvis.alpha.buddy`, `com.jarvis.alpha.executor`, `com.jarvis.alpha.watchdog`, `com.jarvis.alpha.gateway`, `com.jarvis.alpha.fluentbit`, `com.jarvis.alpha.loki`.

These are deployed and working. Rename to categorical form is tracked as **TD-110** — requires coordinated bootout/bootstrap across nodes.

## Deploy targets

| Plist | Node | Load mechanism |
|---|---|---|
| `com.jarvis.alpha.brain.plist` | Brain | `launchctl bootstrap` via start script |
| `com.jarvis.alpha.buddy.plist` | Brain | `launchctl bootstrap` via start script |
| `com.jarvis.alpha.executor.plist` | Brain | `launchctl bootstrap` via start script |
| `com.jarvis.alpha.watchdog.plist` | Brain | `launchctl bootstrap` via start script |
| `com.jarvis.alpha.temporal.server.plist` | Brain | `launchctl bootstrap` via start script |
| `com.jarvis.alpha.temporal.ui.plist` | Brain | `launchctl bootstrap` via start script |
| `com.jarvis.alpha.temporal.worker.plist` | Brain | `launchctl bootstrap` via start script |
| `com.jarvis.alpha.gateway.plist` | Gateway | `launchctl bootstrap` via start script |
| `com.jarvis.alpha.rotate.brain_service.plist` | Brain | Scheduled (StartInterval=86400) |
| `com.jarvis.alpha.rotate.buddy.plist` | Brain | Scheduled |
| `com.jarvis.alpha.rotate.endpoint.plist` | Endpoint | Scheduled |
| `com.jarvis.alpha.rotate.gateway.plist` | Gateway | Scheduled |
| `com.jarvis.alpha.rotate.sandbox.plist` | Sandbox | Scheduled |
| `com.jarvis.alpha.sweep-cert-renewal.brain.plist` | Brain | Scheduled — Sweep TLS certificate renewal for Brain |
| `com.jarvis.alpha.sweep-cert-renewal.gateway.plist` | Gateway | Scheduled — Sweep TLS certificate renewal for Gateway |
| `com.jarvis.alpha.sweep-cert-renewal.endpoint.plist` | Endpoint | Scheduled — Sweep TLS certificate renewal for Endpoint |
| `com.jarvis.alpha.sweep-cert-renewal.sandbox.plist` | Sandbox | Scheduled — Sweep TLS certificate renewal for Sandbox |
| `com.jarvis.alpha.power.brain.plist` | Brain | KeepAlive — via `scripts/install_power_sampler.sh` |
| `com.jarvis.alpha.power.gateway.plist` | Gateway | KeepAlive — via `scripts/install_power_sampler.sh` |
| `com.jarvis.alpha.power.endpoint.plist` | Endpoint | KeepAlive — via `scripts/install_power_sampler.sh` |
| `com.jarvis.alpha.power.sandbox.plist` | Sandbox | KeepAlive — via `scripts/install_power_sampler.sh` |
| `com.jarvis.alpha.fluentbit.plist` | Brain | KeepAlive — log shipper to Loki |
| `com.jarvis.alpha.loki.plist` | Brain | KeepAlive — log aggregator |
| `com.jarvis.alpha.gmail-health.template.plist` | Brain | Template — scheduled Gmail OAuth health watcher |
| `com.jarvis.alpha.beacon-quality.template.plist` | Brain | Template — scheduled Beacon deterministic quality canary |

## External config sync

Observability config templates are versioned in the repo and rendered to their
runtime paths by `scripts/jarvisalpha_pull.sh` when Brain pulls an observability
change. Runtime-specific values come from the node environment with conservative
loopback defaults (`JARVIS_ALPHA_LOKI_HOST`, `JARVIS_ALPHA_LOKI_*_ADDRESS`):

| Repo path | Runtime path |
|---|---|
| `config/observability/brain/fluent-bit.yaml` | `~/fluent-bit/fluent-bit.yaml` |
| `config/observability/brain/loki-config.yaml` | `~/jarvis/loki/loki-config.yaml` |

Changing either repo template restarts `com.jarvis.alpha.fluentbit` and
`com.jarvis.alpha.loki` on Brain during deploy.

## Adding a new plist

1. Name file by Label key: `com.jarvis.alpha.<category>.<name>.plist`
2. Use existing plist as template
3. Validate with `plutil -lint launchagents/<filename>.plist`
4. Update this README's Deploy targets table
5. Commit — TD-107 commit script classifier will fan out deploy

## Drift audit

Use the ownership map in `scripts/install_launchagents.py` for machine-readable
audits:

```bash
python3 scripts/audit_launchagent_drift.py --node brain
```

Add `--strict` when using the audit as a smoke or CI gate.

## Related tech debt

- **TD-110** — Rename legacy labels to categorical form (`.service.`, `.observability.`, `.telemetry.`) — maintenance window work
- **TD-111** — Closed: external Fluent Bit and Loki configs now live under `config/observability/brain/` and sync during Brain deploy
