"""Auto brain vault contract.

This module validates the curated Auto context interface that Spark may read.
It returns metadata only: no raw vault note content is exposed by route payloads
or readiness checks.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

DEFAULT_PERSONALITY_VAULT = "~/jarvis-personality"
AUTO_SPARK_CONTEXT_PATH = Path("auto/interfaces/spark_context.yml")
AUTO_PROMPT_MAX_LINES = 24
AUTO_PROMPT_LINE_MAX_CHARS = 180
AUTO_PROMPT_ALLOWED_HEADINGS = {
    "auto/mission.md": {"Primary Jobs", "Operating Bias", "Non-Goals"},
    "auto/context/current_state.md": {"Active Focus", "Known Live Gates"},
    "auto/context/open_loops.md": {"Spark", "Auto Brain"},
}
AUTO_PROMPT_BLOCKED_LINE = re.compile(
    r"\b(password|token|secret|private body|raw thread|contact detail)\b",
    re.IGNORECASE,
)


class AutoBrainConfigError(RuntimeError):
    """Raised when the Auto brain vault contract is missing or unsafe."""


class AutoBrainSourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str
    byte_count: int
    heading: str | None


class AutoSparkRuntimeMode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spark_can_read: bool
    spark_can_write: bool
    durable_memory_writes: bool
    outbound_send_allowed: bool


class AutoSparkContextMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    allowed_for: list[str]
    source_count: int
    rule_count: int
    sources: list[AutoBrainSourceMetadata]
    runtime_mode: AutoSparkRuntimeMode
    body_access: bool = False
    raw_content_returned: bool = False


class AutoSparkPromptContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: AutoSparkContextMetadata
    prompt_lines: list[str]
    prompt_sha256: str


def load_auto_spark_context(
    vault_root: str | Path | None = None,
) -> AutoSparkContextMetadata:
    """Load and validate Auto's curated Spark-facing context contract."""

    root, manifest = _load_manifest(vault_root)
    return _context_metadata(root, manifest)


def load_auto_spark_prompt_context(
    vault_root: str | Path | None = None,
) -> AutoSparkPromptContext:
    """Load bounded Auto context lines for internal Spark draft prompts."""

    root, manifest = _load_manifest(vault_root)
    metadata = _context_metadata(root, manifest)
    lines = _prompt_lines(root, manifest)
    prompt_text = "\n".join(lines)
    return AutoSparkPromptContext(
        metadata=metadata,
        prompt_lines=lines,
        prompt_sha256=hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
    )


def _load_manifest(vault_root: str | Path | None) -> tuple[Path, dict[str, Any]]:
    root = _vault_root(vault_root)
    return root, _parse_simple_yaml(_read_required(root / AUTO_SPARK_CONTEXT_PATH))


def _context_metadata(
    root: Path,
    manifest: dict[str, Any],
) -> AutoSparkContextMetadata:
    """Validate the Auto Spark contract and return route-safe metadata."""

    allowed_for = _string_list(manifest.get("allowed_for"))
    if "spark-draft" not in allowed_for:
        raise AutoBrainConfigError("auto_spark_context_missing_spark_draft")

    read_sources = _string_list(manifest.get("read_sources"))
    if not read_sources:
        raise AutoBrainConfigError("auto_spark_context_missing_sources")

    runtime_mode = _runtime_mode(manifest.get("runtime_mode"))
    if not runtime_mode.spark_can_read:
        raise AutoBrainConfigError("auto_spark_context_read_disabled")
    if runtime_mode.spark_can_write:
        raise AutoBrainConfigError("auto_spark_context_write_enabled")
    if runtime_mode.durable_memory_writes:
        raise AutoBrainConfigError("auto_spark_context_memory_write_enabled")
    if runtime_mode.outbound_send_allowed:
        raise AutoBrainConfigError("auto_spark_context_send_enabled")

    sources = [_source_metadata(root, source) for source in read_sources]
    return AutoSparkContextMetadata(
        version=str(manifest.get("version") or "unknown"),
        allowed_for=allowed_for,
        source_count=len(sources),
        rule_count=len(_string_list(manifest.get("rules"))),
        sources=sources,
        runtime_mode=runtime_mode,
    )


def _prompt_lines(root: Path, manifest: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for rule in _string_list(manifest.get("rules")):
        clean = _safe_prompt_line(rule)
        if clean:
            lines.append(f"Rule: {clean}")

    for raw_source in _string_list(manifest.get("read_sources")):
        relative = _safe_relative_path(raw_source)
        text = _read_required(root / relative)
        allowed_headings = AUTO_PROMPT_ALLOWED_HEADINGS.get(relative.as_posix())
        if not allowed_headings:
            continue
        for bullet in _markdown_section_bullets(text, allowed_headings):
            clean = _safe_prompt_line(bullet)
            if clean:
                lines.append(clean)

    deduped: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(line)
        if len(deduped) >= AUTO_PROMPT_MAX_LINES:
            break
    if not deduped:
        raise AutoBrainConfigError("auto_spark_context_prompt_empty")
    return deduped


def _markdown_section_bullets(text: str, allowed_headings: set[str]) -> list[str]:
    bullets: list[str] = []
    capture = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("## "):
            heading = stripped.removeprefix("## ").strip()
            capture = heading in allowed_headings
            continue
        if capture and stripped.startswith("- "):
            bullets.append(stripped.removeprefix("- ").strip())
    return bullets


def _safe_prompt_line(value: str) -> str:
    clean = re.sub(r"\s+", " ", value).strip().strip("\"'")
    if not clean or "<FILL_IN" in clean:
        return ""
    if AUTO_PROMPT_BLOCKED_LINE.search(clean):
        return ""
    if len(clean) > AUTO_PROMPT_LINE_MAX_CHARS:
        clean = clean[: AUTO_PROMPT_LINE_MAX_CHARS - 3].rstrip() + "..."
    return clean


def _vault_root(vault_root: str | Path | None) -> Path:
    raw = (
        str(vault_root)
        if vault_root is not None
        else os.environ.get("SPARK_PERSONALITY_VAULT")
        or os.environ.get("JARVIS_PERSONALITY_VAULT")
        or DEFAULT_PERSONALITY_VAULT
    )
    return Path(raw).expanduser()


def _read_required(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise AutoBrainConfigError("auto_brain_file_missing") from exc


def _source_metadata(root: Path, raw_path: str) -> AutoBrainSourceMetadata:
    relative = _safe_relative_path(raw_path)
    path = root / relative
    text = _read_required(path)
    return AutoBrainSourceMetadata(
        path=relative.as_posix(),
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        byte_count=len(text.encode("utf-8")),
        heading=_first_heading(text),
    )


def _safe_relative_path(raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise AutoBrainConfigError("auto_brain_path_not_allowed")
    if candidate.parts[:1] not in {("auto",), ("04_delegation",)}:
        raise AutoBrainConfigError("auto_brain_path_outside_allowlist")
    return candidate


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        clean = line.strip()
        if clean.startswith("# "):
            return clean.removeprefix("# ").strip() or None
    return None


def _runtime_mode(value: Any) -> AutoSparkRuntimeMode:
    if not isinstance(value, dict):
        raise AutoBrainConfigError("auto_spark_context_runtime_mode_missing")
    return AutoSparkRuntimeMode(
        spark_can_read=_bool(value.get("spark_can_read")),
        spark_can_write=_bool(value.get("spark_can_write")),
        durable_memory_writes=_bool(value.get("durable_memory_writes")),
        outbound_send_allowed=_bool(value.get("outbound_send_allowed")),
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse the tiny YAML subset used by the Auto Spark context manifest."""

    data: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" ") and ":" in line:
            key, raw_value = line.split(":", 1)
            current_key = key.strip()
            value = _scalar(raw_value.strip())
            data[current_key] = [] if value is None else value
            continue
        if current_key is None:
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            if not isinstance(data.get(current_key), list):
                data[current_key] = []
            data[current_key].append(_scalar(stripped.removeprefix("- ").strip()))
            continue
        if ":" in stripped:
            if not isinstance(data.get(current_key), dict):
                data[current_key] = {}
            key, raw_value = stripped.split(":", 1)
            data[current_key][key.strip()] = _scalar(raw_value.strip())
    return data


def _scalar(value: str) -> Any:
    if value == "":
        return None
    clean = value.strip().strip("\"'")
    lowered = clean.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return clean
