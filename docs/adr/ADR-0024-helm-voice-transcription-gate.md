# ADR-0024: Helm Voice Transcription Gate

## Status

Accepted

## Context

Helm's Ask surface now has AT-0 push-to-talk UI, but browser speech input needs a
server-side transcription endpoint. The existing Family voice service already
owns local audio mechanics, but it enforces Family-specific token and child voice
policy. Helm is an Alpha-brokered workspace and authenticates through the Alpha
session cookie.

Directly calling a Family or future AT-0 voice service from Helm would require
extra browser-visible service credentials or service-specific auth logic in the
Helm frontend.

## Decision

Alpha provides `POST /v1/helm/voice/transcribe` as a narrow gate for Helm voice
input. The route:

- Requires the existing Alpha session and `helm.read` or `admin` scope.
- Validates audio content type and max upload size before forwarding.
- Forwards to a configured backend URL using either a configured backend token
  or the caller's Alpha JWT.
- Fails closed with `voice_transcription_unconfigured` when no backend is set.
- Does not persist raw audio or transcripts.

The backend is configured by environment:

- `JARVIS_HELM_VOICE_TRANSCRIBE_URL`
- `JARVIS_HELM_VOICE_BACKEND_TOKEN` or `JARVIS_HELM_VOICE_BACKEND_TOKEN_SECRET`
- `JARVIS_HELM_VOICE_BACKEND_FIELD`
- `JARVIS_HELM_VOICE_VERIFY_TLS`
- `JARVIS_HELM_VOICE_TIMEOUT_SECS`
- `JARVIS_HELM_VOICE_MAX_AUDIO_BYTES`

## Consequences

Helm can enable push-to-talk by setting its runtime `voiceInputUrl` to the Alpha
route, while Alpha remains the broker of trust. The actual transcription backend
can be Family voice for a pilot or a dedicated AT-0 voice service later without
changing the Helm frontend.

The route does not create a transcription model inside Alpha. If no backend is
configured, voice input remains visibly unavailable rather than silently failing.

## Rollback

Remove the Helm runtime `voiceInputUrl` value to hide push-to-talk. The route can
remain mounted because it fails closed without backend configuration.
