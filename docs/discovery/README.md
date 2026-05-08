# Discovery reports

This directory contains point-in-time state captures of jarvis-alpha — typically run via Claude Code before a deployment, schema migration, or architectural decision. Each report is dated and immutable; superseded reports are NOT deleted.

## Naming

`DISCOVERY_<YYYY-MM-DD>_<context>.md`

Examples:
- `DISCOVERY_2026-05-08_pre-slab6a.md` — Pre-Slab-6a state verification (services, RLS policies, SECDEF functions, smoke harness, trait drift).

## Why these are committed

- Future sessions can search past discoveries via `grep -r` instead of re-running expensive introspection.
- Pattern of "live state vs handoff text" drift is documented historically — discovery reports are the truth source at moment of capture.
- jarvis_branch and jarvis_pr both reject untracked state as "dirty"; committing eliminates that friction (TD-205 from 2026-05-08).

## When to add

Before any non-trivial deployment or design session that benefits from grounding decisions in current reality. Discovery is cheap; assumptions are expensive.
