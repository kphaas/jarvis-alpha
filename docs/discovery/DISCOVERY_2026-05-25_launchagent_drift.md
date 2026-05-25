# LaunchAgent Drift Audit — TD-122

Date: 2026-05-25  
Repo: `jarvis-alpha`  
Issue: TD-122 / GitHub #62

## Finding

The original drift report compared every plist in `launchagents/` against Brain's loaded LaunchAgents. That over-counted drift because several repo plists are intentionally node-owned by Gateway, Endpoint, or Sandbox.

The canonical ownership source is now explicit:

- `scripts/install_launchagents.py::SERVICE_NODE_MAP` defines which node owns each service label.
- `scripts/audit_launchagent_drift.py` compares that expected set with live `launchctl list` output.
- `launchagents/README.md` remains the human-readable deploy target table.

## Four-Lens Decision

- CIO: Treat cross-node plist differences as expected ownership first, not outage noise.
- EA: Keep one machine-readable ownership map and audit from it.
- AI Solo Developer: Add a reusable audit command so future sessions do not repeat manual plist diffing.
- Code Production: Make the audit read-only by default, with `--strict` available for CI or smoke gates.

## Runbook

On any node:

```bash
cd ~/jarvis-alpha
python3 scripts/audit_launchagent_drift.py --node brain
```

For machine-readable output:

```bash
python3 scripts/audit_launchagent_drift.py --node brain --json
```

For a fail-fast gate:

```bash
python3 scripts/audit_launchagent_drift.py --node brain --strict
```

## Expected Brain-Owned Labels

- `com.jarvis.alpha.brain`
- `com.jarvis.alpha.buddy`
- `com.jarvis.alpha.executor`
- `com.jarvis.alpha.fluentbit`
- `com.jarvis.alpha.loki`
- `com.jarvis.alpha.power.brain`
- `com.jarvis.alpha.rotate.brain_service`
- `com.jarvis.alpha.rotate.buddy`
- `com.jarvis.alpha.school-email`
- `com.jarvis.alpha.temporal.server`
- `com.jarvis.alpha.temporal.ui`
- `com.jarvis.alpha.temporal.worker`
- `com.jarvis.alpha.watchdog`

## Resolution

TD-122 is resolved by replacing the manual audit with a repeatable script and documenting node ownership semantics. Any actual live drift found by the script should be handled as a separate deploy/LaunchAgent installation task.
