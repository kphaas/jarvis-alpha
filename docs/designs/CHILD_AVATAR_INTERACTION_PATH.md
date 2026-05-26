# Child Avatar Interaction Path

Status: v0.1 design note
Date: 2026-05-26
Scope: Alpha child-facing avatar and voice interaction for Ryleigh and Sloane

## Goal

Create a warm, expressive child-facing Alpha surface that can speak, listen,
and show a simple animated presence while keeping all safety, policy, memory,
and audit decisions in Alpha Brain.

The first visual can be a pulsing neural-network style avatar: abstract,
calm, and emotionally responsive without pretending to be a human.

## Four-Lens Decision

| Lens | Choice |
|---|---|
| CIO | Child safety, auditability, and parent visibility outrank novelty. The avatar is a client of Alpha, not an independent authority. |
| Enterprise Architect | Avatar node handles presentation, STT/TTS, and animation. Brain owns auth, child profile policy, model routing, memory, and logging. |
| AI Solo Developer | Start with a web avatar surface before robotics or complex 3D. Use local-first voice components and one narrow API contract. |
| Code Production | Every request carries child identity, session id, surface id, and requested mode. No raw child audio is retained by default. |

## Target Shape

```
Child voice/tablet
  -> Avatar client
  -> Brain child interaction API
  -> child policy gate
  -> local/cloud model routing
  -> age-filtered response
  -> TTS + animated avatar reply
```

## Build Steps

1. Define the child interaction contract.
   - Request fields: `child_profile`, `surface_id`, `mode`, `transcript`, `session_id`.
   - Response fields: `reply_text`, `voice_style`, `avatar_state`, `parent_visible_summary`.
   - Modes: story, homework_help, draw_with_me, bedtime, safe_ask.

2. Build the Brain policy route first.
   - Enforce existing child profile scopes.
   - Sloane and Ryleigh get different max rating and reading levels.
   - T3+ actions stay blocked unless explicitly parent-approved.
   - Cloud escalation requires parent policy; local model is default.

3. Build the avatar client.
   - First version: Endpoint-hosted web UI at child-safe route.
   - Visual: pulsing neural network canvas with 4 states: listening, thinking,
     speaking, paused.
   - Tablet mode and voice mode use the same Brain API.

4. Add voice.
   - STT: Whisper local or Apple Speech as an adapter.
   - TTS: Kokoro local first; voice style selected by Brain response.
   - Push-to-talk first; wake word later after privacy review.

5. Add personality safely.
   - Store persona prompts in the personality vault and compile them into a
     child-safe system prompt.
   - The persona can be warm, playful, patient, and gentle, but must never
     present as a parent, doctor, therapist, teacher of record, or authority.

6. Add parent visibility.
   - Persist derived summaries, not raw audio.
   - Parent dashboard shows activity summary and any blocked/denied requests.
   - Mattermost can receive parent-visible alerts for denied or concerning
     child requests.

7. Soak before expanding.
   - Start with Ken-only demo mode.
   - Then parent-supervised child sessions.
   - Only after soak: bedtime routine, story mode, drawing mode, and homework
     helper.

## Initial Avatar States

| State | Visual | Voice behavior |
|---|---|---|
| idle | slow pulse, low brightness | silent |
| listening | brighter pulse, waveform input | capture until push-to-talk release |
| thinking | node links ripple inward | no filler speech unless response exceeds threshold |
| speaking | pulse follows TTS amplitude | speak age-filtered reply |
| paused | dim steady glow | tells child to ask Ken if needed |

## Non-Negotiables

- No autonomous outbound communication from child avatar.
- No raw child audio retention by default.
- No adult topics for child profiles.
- No medical advice beyond parent-approved safe wording.
- No hidden memory writes; parent-visible summaries only.
- No direct smart-home, network, email, or iMessage actions from the avatar.

## First Implementation Slice

The first shippable slice should be visual + text-only:

1. Brain route for `child.safe_ask` with policy stub and local-model response.
2. Endpoint `/kids/avatar` visual with pulsing neural-network states.
3. Parent-visible event row for each interaction summary.
4. No microphone, no TTS, no cloud escalation.

Voice comes second, after the route and visual safety posture are proven.

