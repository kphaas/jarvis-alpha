"""Read-only Spark persona grounding for Alpha memory prompts.

This module intentionally does not write Alpha memory. It creates a bounded
identity lane from the reviewed jarvis-personality vault so Ask/Chat can be
grounded without competing with semantic-memory recency caps.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from brain.services.spark_voice_feedback import (
    DEFAULT_FEEDBACK_ROOT,
    FEEDBACK_FILENAME,
    JARVIS_FEEDBACK_ROOT_ENV,
    SPARK_FEEDBACK_ROOT_ENV,
)
from brain.services.spark_voice_ingest import (
    DEFAULT_PERSONALITY_VAULT,
    SparkVoiceIngestError,
    load_spark_voice_guidance,
)

GROUNDING_MAX_LINES = 18
GROUNDING_LINE_MAX_CHARS = 180
BOUNDARY_HEADINGS = {"Hard Boundaries", "Extra Caution Topics", "Default On Ambiguity"}
ALLOWED_PRINCIPAL = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
BLOCKED_LINE = re.compile(
    r"\b(password|token|secret|private key|raw thread|contact detail|phone number)\b",
    re.IGNORECASE,
)


class SparkMemoryGroundingError(RuntimeError):
    """Raised when Spark grounding cannot be loaded safely."""


@dataclass(frozen=True, slots=True)
class SparkMemoryGrounding:
    principal_id: str
    lines: tuple[str, ...]
    personality_root: str
    feedback_root: str
    feedback_count: int

    def to_context_block(self) -> str:
        body = "\n".join(f"- {line}" for line in self.lines)
        return f"[WHO YOU'RE TALKING TO]\n{body}"


def load_spark_memory_grounding(
    *,
    principal_id: str | None,
    vault_root: str | Path | None = None,
    feedback_root: str | Path | None = None,
) -> SparkMemoryGrounding | None:
    """Load bounded, reviewed persona context for one principal."""

    principal = _safe_principal(principal_id)
    if principal is None:
        return None

    root = _personality_root(vault_root)
    guidance = load_spark_voice_guidance(root, principal)
    boundary_lines = _boundary_lines(root, principal)
    feedback = _feedback_root(feedback_root)
    feedback_count = _feedback_count(feedback, principal)

    lines = _dedupe_lines(
        [
            f"Principal: {principal}.",
            "Spark/persona grounding is read-only context, not permission to send or store new memory.",
            f"Voice target: {', '.join(guidance.voice_markers[:8])}.",
            f"Avoid sounding: {', '.join(guidance.avoid_markers[:8])}.",
            f"Use signature phrases sparingly: {', '.join(guidance.recurring_phrases[:6])}.",
            *_channel_lines(guidance.channel_style),
            *_judgment_lines(guidance.judgment_style),
            *_accessibility_lines(guidance.accessibility_style),
            *boundary_lines,
            f"Draft edit feedback waiting for review: {feedback_count}.",
        ]
    )
    if not lines:
        raise SparkMemoryGroundingError("spark_memory_grounding_empty")

    return SparkMemoryGrounding(
        principal_id=principal,
        lines=tuple(lines[:GROUNDING_MAX_LINES]),
        personality_root=str(root),
        feedback_root=str(feedback),
        feedback_count=feedback_count,
    )


def collect_spark_memory_grounding_status(
    *,
    principal_id: str = "ken",
    vault_root: str | Path | None = None,
    feedback_root: str | Path | None = None,
) -> dict[str, object]:
    """Return Buddy-safe status without exposing raw persona file content."""

    principal = _safe_principal(principal_id) or "unknown"
    try:
        grounding = load_spark_memory_grounding(
            principal_id=principal,
            vault_root=vault_root,
            feedback_root=feedback_root,
        )
    except (SparkMemoryGroundingError, SparkVoiceIngestError, OSError) as exc:
        return {
            "principal_id": principal,
            "status": "unavailable",
            "error_class": exc.__class__.__name__,
            "line_count": 0,
            "feedback_count": 0,
        }
    if grounding is None:
        return {
            "principal_id": principal,
            "status": "skipped",
            "line_count": 0,
            "feedback_count": 0,
        }
    return {
        "principal_id": principal,
        "status": "ok",
        "line_count": len(grounding.lines),
        "feedback_count": grounding.feedback_count,
    }


def _safe_principal(principal_id: str | None) -> str | None:
    clean = (principal_id or "").strip().lower()
    if not clean or clean in {"anon", "unknown", "system"}:
        return None
    if not ALLOWED_PRINCIPAL.fullmatch(clean):
        return None
    return clean


def _personality_root(vault_root: str | Path | None) -> Path:
    raw = (
        str(vault_root)
        if vault_root is not None
        else os.environ.get("SPARK_PERSONALITY_VAULT")
        or os.environ.get("JARVIS_PERSONALITY_VAULT")
        or DEFAULT_PERSONALITY_VAULT
    )
    return Path(raw).expanduser()


def _feedback_root(feedback_root: str | Path | None) -> Path:
    raw = (
        str(feedback_root)
        if feedback_root is not None
        else os.environ.get(SPARK_FEEDBACK_ROOT_ENV)
        or os.environ.get(JARVIS_FEEDBACK_ROOT_ENV)
        or DEFAULT_FEEDBACK_ROOT
    )
    return Path(raw).expanduser()


def _feedback_count(feedback_root: Path, principal_id: str) -> int:
    path = (
        feedback_root
        / "spark"
        / "principals"
        / principal_id
        / "feedback"
        / FEEDBACK_FILENAME
    )
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)
    except FileNotFoundError:
        return 0


def _boundary_lines(root: Path, principal_id: str) -> list[str]:
    path = root / "spark" / "principals" / principal_id / "boundaries.md"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    bullets = _markdown_section_bullets(text, BOUNDARY_HEADINGS)
    return [f"Boundary: {bullet}" for bullet in bullets]


def _channel_lines(channel_style: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for channel in ("Text", "Email", "AI chat"):
        rule = channel_style.get(channel)
        if rule:
            lines.append(f"{channel}: {rule}")
    return lines


def _judgment_lines(judgment_style: dict[str, str]) -> list[str]:
    lines: list[str] = []
    for situation in ("Uncertainty", "Disagreement", "Saying no", "Urgency"):
        rule = judgment_style.get(situation)
        if rule:
            lines.append(f"{situation}: {rule}")
    return lines


def _accessibility_lines(accessibility_style: tuple[str, ...]) -> list[str]:
    if not accessibility_style:
        return []
    return [f"Accessibility preference: {', '.join(accessibility_style[:6])}."]


def _markdown_section_bullets(text: str, headings: set[str]) -> list[str]:
    bullets: list[str] = []
    capture = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("## "):
            capture = stripped.removeprefix("## ").strip() in headings
            continue
        if capture and stripped.startswith("- "):
            bullets.append(stripped.removeprefix("- ").strip())
        elif capture and stripped and not stripped.startswith("#"):
            bullets.append(stripped)
    return bullets


def _dedupe_lines(values: list[str]) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _safe_line(value)
        if not clean:
            continue
        key = clean.casefold()
        if key in seen:
            continue
        seen.add(key)
        lines.append(clean)
    return lines


def _safe_line(value: str) -> str:
    clean = re.sub(r"\s+", " ", value).strip().strip("\"'")
    if not clean or "<FILL_IN" in clean:
        return ""
    if BLOCKED_LINE.search(clean):
        return ""
    if len(clean) > GROUNDING_LINE_MAX_CHARS:
        clean = clean[: GROUNDING_LINE_MAX_CHARS - 3].rstrip() + "..."
    return clean
