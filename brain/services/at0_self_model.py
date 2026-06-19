"""Runtime-grounded AT-0 identity and capability model."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from brain.services.internet_scout.health import build_beacon_health

CapabilityStatus = Literal["ok", "degraded", "unavailable", "planned"]


class At0SelfIdentity(BaseModel):
    user_facing_name: str = "AT-0"
    accepted_names: list[str] = Field(default_factory=lambda: ["AT-0", "Otto", "Auto"])
    backend_identity: str = "JARVIS/Alpha"
    owner: str = "Kenneth Haas"
    summary: str = (
        "AT-0 is Ken's Helm chat, voice, and avatar companion. JARVIS/Alpha is "
        "the private self-hosted infrastructure behind it."
    )


class At0Capability(BaseModel):
    id: str
    name: str
    status: CapabilityStatus
    summary: str
    limits: list[str] = Field(default_factory=list)


class At0Mode(BaseModel):
    id: str
    name: str
    status: CapabilityStatus
    summary: str


class At0SelfModel(BaseModel):
    service: str = "at0-self-model"
    generated_at: str
    identity: At0SelfIdentity
    modes: list[At0Mode]
    capabilities: list[At0Capability]
    current_limits: list[str] = Field(default_factory=list)
    prompt_context: str


_SELF_QUERY_RE = re.compile(
    r"\b("
    r"who\s+are\s+you|what\s+are\s+you|what\s+is\s+(?:at-?0|otto|auto|jarvis)|"
    r"are\s+you\s+(?:jarvis|otto|auto|at-?0)|"
    r"what\s+can\s+you\s+do|what\s+are\s+your\s+capabilit(?:y|ies)|"
    r"what\s+do\s+you\s+know\s+about\s+me|"
    r"do\s+you\s+know\s+(?:things|anything)\s+about\s+me|"
    r"what\s+modes?\s+(?:do\s+you\s+have|are\s+available)|"
    r"can\s+you\s+(?:search|browse|use\s+the\s+web|access\s+the\s+internet|talk|speak|hear|listen|remember|use\s+memory|read\s+documents|use\s+the\s+vault)|"
    r"how\s+(?:do|can)\s+i\s+(?:make\s+you\s+|turn\s+on\s+|enable\s+)?(?:search(?:\s+(?:the\s+)?internet)?|browse|use\s+(?:the\s+)?web|access\s+(?:the\s+)?internet|use\s+beacon|web\s+search)|"
    r"do\s+you\s+have\s+(?:web|internet|voice|memory|avatar|vault)|"
    r"how\s+do\s+you\s+work|what\s+is\s+your\s+setup|learn\s+about\s+yourself"
    r")\b",
    re.IGNORECASE,
)


def is_at0_self_query(query: str) -> bool:
    """Return true when the user is asking about AT-0's identity/capabilities."""
    return bool(_SELF_QUERY_RE.search(" ".join(query.split())))


async def build_at0_self_model(conn: object | None = None) -> At0SelfModel:
    """Build AT-0's self model from bounded static facts and live health."""
    identity = At0SelfIdentity()
    beacon = await _beacon_capability(conn)
    voice_in = _voice_input_capability()
    voice_out = _voice_output_capability()
    modes = _modes(voice_in=voice_in, voice_out=voice_out)
    capabilities = [
        At0Capability(
            id="chat",
            name="Chat answers",
            status="ok",
            summary="Answer in Helm Ask with memory/context and bounded personality style.",
            limits=[
                "Uses approved memory for stable personal context only.",
                "Does not treat memory as proof for current public facts.",
            ],
        ),
        voice_in,
        voice_out,
        At0Capability(
            id="avatar",
            name="Avatar presence",
            status="ok",
            summary="Use the 2D/3D Helm avatar surfaces when the frontend mode enables them.",
            limits=[
                "Avatar mode is a presentation surface; it does not expand authority."
            ],
        ),
        beacon,
        At0Capability(
            id="memory",
            name="Memory grounding",
            status="ok",
            summary="Use Alpha memory for stable personal context and preferences.",
            limits=[
                "Volatile capability status comes from live health, not memory.",
                "Memory must not override Beacon evidence for current/public claims.",
            ],
        ),
        At0Capability(
            id="vault",
            name="Vault and documents",
            status="ok",
            summary="Work with approved Alpha vault document upload, recall, and digest surfaces when authorized.",
            limits=[
                "Private document content stays behind Alpha authorization and vault controls."
            ],
        ),
        At0Capability(
            id="helm_domains",
            name="Helm domain summaries",
            status="ok",
            summary="Surface redacted Alpha, Family, Financial, Medical, and action status summaries through Helm.",
            limits=["Mutations and high-risk actions require Alpha approval gates."],
        ),
    ]
    current_limits = _current_limits(
        beacon=beacon, voice_in=voice_in, voice_out=voice_out
    )
    prompt_context = _prompt_context(
        identity=identity,
        modes=modes,
        capabilities=capabilities,
        current_limits=current_limits,
    )
    return At0SelfModel(
        generated_at=datetime.now(UTC).isoformat(),
        identity=identity,
        modes=modes,
        capabilities=capabilities,
        current_limits=current_limits,
        prompt_context=prompt_context,
    )


async def _beacon_capability(conn: object | None) -> At0Capability:
    if conn is None:
        return At0Capability(
            id="verified_web",
            name="Verified web / Beacon",
            status="unavailable",
            summary="Beacon health was not checked for this response.",
            limits=["Do not claim live web verification without Beacon evidence."],
        )

    try:
        health = await build_beacon_health(conn)
    except Exception:
        return At0Capability(
            id="verified_web",
            name="Verified web / Beacon",
            status="unavailable",
            summary="Beacon health is unavailable right now.",
            limits=["Fail closed for current public facts instead of guessing."],
        )

    gateway = health.checks.get("gateway")
    metadata = gateway.metadata if gateway else {}
    usable_count = _int_value(metadata.get("usable_provider_count"))
    required_count = _int_value(metadata.get("required_provider_count"))
    provider_order = _string_list(metadata.get("provider_order"))
    status: CapabilityStatus
    if usable_count > 0 and health.status == "ok":
        status = "ok"
    elif usable_count > 0:
        status = "degraded"
    else:
        status = "unavailable"

    provider_text = (
        f"{usable_count}/{required_count or 'unknown'} search providers usable"
        if provider_order
        else "provider health checked"
    )
    return At0Capability(
        id="verified_web",
        name="Verified web / Beacon",
        status=status,
        summary=(
            "Use Alpha Beacon for current/public web claims with accepted evidence "
            f"({provider_text})."
        ),
        limits=[
            "Requires accepted Beacon evidence for verified current/public claims.",
            "Fails closed when source quality is insufficient or providers are unavailable.",
        ],
    )


def _voice_input_capability() -> At0Capability:
    configured = bool(os.getenv("JARVIS_HELM_VOICE_TRANSCRIBE_URL", "").strip())
    return At0Capability(
        id="voice_input",
        name="Voice input",
        status="ok" if configured else "unavailable",
        summary=(
            "Transcribe short Helm microphone audio through Alpha's voice gate."
            if configured
            else "Voice transcription is not configured in this Alpha runtime."
        ),
        limits=["Requires Helm microphone permission and Alpha voice endpoint auth."],
    )


def _voice_output_capability() -> At0Capability:
    configured = bool(os.getenv("JARVIS_HELM_VOICE_SPEAK_URL", "").strip())
    return At0Capability(
        id="voice_output",
        name="Voice output",
        status="ok" if configured else "unavailable",
        summary=(
            "Speak replies through the configured AT-0/Kokoro voice broker."
            if configured
            else "Voice synthesis is not configured in this Alpha runtime."
        ),
        limits=[
            "Selected Helm personality maps to the voice requested from the broker."
        ],
    )


def _modes(*, voice_in: At0Capability, voice_out: At0Capability) -> list[At0Mode]:
    voice_status: CapabilityStatus = (
        "ok"
        if voice_in.status == "ok" and voice_out.status == "ok"
        else "degraded"
        if voice_in.status == "ok" or voice_out.status == "ok"
        else "unavailable"
    )
    return [
        At0Mode(
            id="chat",
            name="Chat",
            status="ok",
            summary="Text chat history, Ask composer, Beacon evidence panels, and memory context.",
        ),
        At0Mode(
            id="voice",
            name="Voice",
            status=voice_status,
            summary="Hands-free spoken turn taking with transcript history and personality voice.",
        ),
        At0Mode(
            id="avatar",
            name="Avatar",
            status="ok",
            summary="Centered AT-0 avatar presentation with spoken replies and minimal chat chrome.",
        ),
    ]


def _current_limits(
    *,
    beacon: At0Capability,
    voice_in: At0Capability,
    voice_out: At0Capability,
) -> list[str]:
    limits = [
        "Use AT-0, Otto, or Auto as the user-facing name; JARVIS is backend infrastructure.",
        "Current/public claims need Beacon evidence or a clear unverified caveat.",
        "Do not invent tools, permissions, memories, or live access that are not in this model.",
    ]
    if beacon.status != "ok":
        limits.append(f"Verified web is {beacon.status}: {beacon.summary}")
    if voice_in.status != "ok" or voice_out.status != "ok":
        limits.append(
            "Voice mode may be degraded if either transcription or synthesis is unavailable."
        )
    return limits


def _prompt_context(
    *,
    identity: At0SelfIdentity,
    modes: list[At0Mode],
    capabilities: list[At0Capability],
    current_limits: list[str],
) -> str:
    mode_lines = "\n".join(
        f"- {mode.name} ({mode.status}): {mode.summary}" for mode in modes
    )
    capability_lines = "\n".join(
        f"- {cap.name} ({cap.status}): {cap.summary}" for cap in capabilities
    )
    limit_lines = "\n".join(f"- {limit}" for limit in current_limits)
    return "\n".join(
        [
            "AT-0 self model (runtime-grounded; not user memory):",
            f"- Identity: {identity.summary}",
            "- Names: AT-0, Otto, and Auto are valid user-facing names. JARVIS is the backend/infrastructure name.",
            "Modes:",
            mode_lines,
            "Capabilities:",
            capability_lines,
            "Current limits:",
            limit_lines,
            "Answer self/capability questions from this context. If a capability is degraded or unavailable, say that plainly.",
        ]
    )


def _int_value(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
