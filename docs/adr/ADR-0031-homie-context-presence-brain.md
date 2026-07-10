# ADR-0031: Homie Context and Presence Brain Boundary

Date: 2026-07-10

Status: Proposed

Related: Homie context/presence brain v1

## Context

Homie sits above Home Assistant and the Gateway. It needs enough household
context to explain home actions and later use presence sensors, without becoming
a second home-control plane.

## Decision

Alpha compiles a `homie_context` payload for Homie intent responses.

- Actor context comes from the trusted Alpha session.
- Room, policy tier, routine, and presence hints come from Gateway state context
  when available.
- Time context is deterministic and uses `JARVIS_HOME_TIME_ZONE` with a named
  default.
- Presence is explicit `unknown/not_connected` until real sensors provide a
  signal.
- Gateway remains the final policy and execution authority.

## Boundaries

- Alpha does not call Home Assistant directly.
- Alpha does not infer physical presence from chat activity.
- Alpha does not change the Gateway action request body in this phase.
- Home Assistant remains the source of state and device execution.

## Consequences

- Helm and AT-0 can show a plain-English explanation for actions.
- Future presence sensors have a stable response contract to populate.
- Existing Gateway behavior remains backwards-compatible if it ignores Alpha
  context.
