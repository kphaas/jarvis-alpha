# Handoff — Complete LaunchAgent Templating for Brain / Endpoint / Sandbox

**Created:** 2026-04-20 during Gateway M1→M4 hardware swap session.
**Status:** Gateway 3 plists migrated, pattern proven. Other nodes pending.

## Context

On 2026-04-20, Gateway hardware was swapped from an M1 Mac Mini (user `infranet`)
to an M4 Mac Mini (user `gate`). All 19 launchd plists in `launchagents/` had
hardcoded absolute paths coupled to the macOS usernames of each node:

| User | Node | # of plists |
|---|---|---|
| `infranet` | Gateway | 3 |
| `jarvisbrain` | Brain | 9 (incl. temporal, loki, fluentbit, watchdog) |
| `jarvisendpoint` | Endpoint | 2 |
| `jarvissand` | Sandbox | 2 |

This coupled the repo to specific machines. Hardware swaps required manual editing
of plist files. That was recognized as tech debt and fixed for Gateway only during
the swap session.

Pattern adopted: **templates in git, rendered at install time by a generator script**.
Matches Helm, Kustomize, and standard 12-factor deployment practice.

## What's already done (Gateway)

- `launchagents/com.jarvis.alpha.gateway.template.plist` (replaces `.plist`)
- `launchagents/com.jarvis.alpha.power.gateway.template.plist`
- `launchagents/com.jarvis.alpha.rotate.gateway.template.plist`
- `scripts/install_launchagents.py` — auto-detects `$HOME`/`$USER`, supports `--home`, `--user`, `--node`, `--dry-run`, `--list`
- `.gitignore` updated — rendered `*.plist` ignored; `*.template.plist` tracked
- README documents the pattern
- Installer validates rendered plists via `plistlib.loads` before writing
- Installer logs structured JSON matching Alpha's `JarvisFormatter` pattern

## What this handoff needs to accomplish

Migrate the remaining 16 plists to templates. Verify each machine can reinstall
its plists via `scripts/install_launchagents.py --node <n>` after pulling latest.

### Plists to templatize

**Brain (11):**
- com.jarvis.alpha.brain.plist
- com.jarvis.alpha.buddy.plist
- com.jarvis.alpha.executor.plist
- com.jarvis.alpha.fluentbit.plist
- com.jarvis.alpha.loki.plist
- com.jarvis.alpha.power.brain.plist
- com.jarvis.alpha.rotate.brain_service.plist
- com.jarvis.alpha.rotate.buddy.plist
- com.jarvis.alpha.temporal.server.plist
- com.jarvis.alpha.temporal.ui.plist
- com.jarvis.alpha.watchdog.plist

**Endpoint (2):**
- com.jarvis.alpha.power.endpoint.plist
- com.jarvis.alpha.rotate.endpoint.plist

**Sandbox (2) — note: Sandbox role is currently vacant, these templates are for future re-use:**
- com.jarvis.alpha.power.sandbox.plist
- com.jarvis.alpha.rotate.sandbox.plist

## Steps per node

For each plist:

1. Read the current plist file
2. Rename `com.jarvis.alpha.<n>.plist` -> `com.jarvis.alpha.<n>.template.plist`
3. Replace every `/Users/<user>/` with `{{HOME}}/`
4. Validate rendered output:
```bash
   python3 scripts/install_launchagents.py --dry-run --node brain
```
5. Commit the template changes as one commit per node, e.g. `chore: templatize Brain plists`

Then on each physical machine (SSH into brain / endpoint / sandbox):

```bash
cd ~/jarvis-alpha
git pull
python3 scripts/install_launchagents.py --node <node>

# For each previously-running service:
launchctl unload ~/Library/LaunchAgents/com.jarvis.alpha.<n>.plist
launchctl load ~/Library/LaunchAgents/com.jarvis.alpha.<n>.plist
```

Verify services come back up cleanly via logs.

## Known quirks

- **Brain's fluentbit plist** references `/Users/jarvisbrain/fluent-bit/` (NOT under jarvis-alpha). Two options: add a second placeholder for the fluent-bit config dir, OR document that fluent-bit config must live at `{{HOME}}/fluent-bit/` going forward. Recommend the latter — keep placeholder surface minimal.

- **Brain's loki plist** similarly references `/Users/jarvisbrain/jarvis/loki/`. Same resolution — document standard install location.

- **Brain's temporal.server/ui plists** have TWO user-coupled paths: one to the script and one to `HOME` env var (`<string>/Users/jarvisbrain</string>`). Both need `{{HOME}}`.

## Extension: new placeholders

If future services need paths outside `$HOME`, the installer supports arbitrary
`{{VARNAME}}` placeholders. Add the name + value to the `values` dict in
`install_launchagents.py` and pass at install time.

Keep placeholder count small. More placeholders = more coupling.

## Post-migration validation

Once all 4 nodes migrated:

```bash
cd ~/jarvis-alpha
python3 scripts/install_launchagents.py --list
# Should list 19 templates
grep -rnE '/Users/[a-z]+' launchagents/*.plist 2>/dev/null
# Should return NOTHING — no hardcoded user paths anywhere in templates
```

## ADR followup

After all 4 nodes migrated, add an ADR to `jarvis-standards`:

- **Title**: "Deployment artifacts use templates, not hardcoded paths"
- **Pattern**: macOS plists, systemd units, Dockerfiles all follow the same rule
- **Installer**: single renderer per platform, deterministic from git
- **Related**: ADR-0001 (Docker adoption) — templating is a prerequisite for the
  Docker migration scheduled in Alpha-5
