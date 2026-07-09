"""Budget and label memory context before chat prompt compilation."""

from __future__ import annotations

import re
from dataclasses import dataclass

CHAT_MEMORY_PACK_SCHEMA_VERSION = "chat_memory_pack.v1"
DEFAULT_CHAT_MEMORY_BUDGET_CHARS = 6000

_SECTION_RE = re.compile(r"^\[[A-Z0-9 _/-]+\]$")
_CURRENT_RE = re.compile(r"\[current\]", re.IGNORECASE)
_HISTORICAL_RE = re.compile(r"\[historical\]", re.IGNORECASE)
_NEEDS_REFRESH_RE = re.compile(r"\[needs refresh\]", re.IGNORECASE)


@dataclass(frozen=True)
class ChatMemoryPackManifest:
    source_chars: int
    packed_chars: int
    budget_chars: int
    source_line_count: int
    packed_line_count: int
    dropped_line_count: int
    section_order: tuple[str, ...]
    current_line_count: int
    historical_line_count: int
    needs_refresh_line_count: int
    truncated: bool

    def to_metadata(self) -> dict[str, object]:
        return {
            "chat_memory_pack_schema_version": CHAT_MEMORY_PACK_SCHEMA_VERSION,
            "chat_memory_pack_source_chars": self.source_chars,
            "chat_memory_pack_packed_chars": self.packed_chars,
            "chat_memory_pack_budget_chars": self.budget_chars,
            "chat_memory_pack_source_line_count": self.source_line_count,
            "chat_memory_pack_packed_line_count": self.packed_line_count,
            "chat_memory_pack_dropped_line_count": self.dropped_line_count,
            "chat_memory_pack_section_order": list(self.section_order),
            "chat_memory_pack_current_line_count": self.current_line_count,
            "chat_memory_pack_historical_line_count": self.historical_line_count,
            "chat_memory_pack_needs_refresh_line_count": (
                self.needs_refresh_line_count
            ),
            "chat_memory_pack_truncated": self.truncated,
        }


@dataclass(frozen=True)
class ChatMemoryPack:
    context: str
    manifest: ChatMemoryPackManifest


@dataclass(frozen=True)
class _MemoryLine:
    line_id: int
    section: str | None
    text: str
    priority: int


def pack_chat_memory_context(
    memory_context: str,
    *,
    budget_chars: int = DEFAULT_CHAT_MEMORY_BUDGET_CHARS,
) -> ChatMemoryPack:
    source = _clean_context(memory_context)
    source_lines = source.splitlines() if source else []
    if not source or budget_chars <= 0:
        return _pack_result(
            source=source,
            packed="",
            source_lines=source_lines,
            packed_lines=[],
            budget_chars=budget_chars,
        )

    parsed = _parse_lines(source_lines)
    if len(source) <= budget_chars:
        return _pack_result(
            source=source,
            packed=source,
            source_lines=source_lines,
            packed_lines=parsed,
            budget_chars=budget_chars,
        )

    selected: set[int] = set()
    for line in sorted(parsed, key=lambda item: (item.priority, item.line_id)):
        candidate = _render_selected(parsed, selected | {line.line_id})
        if len(candidate) <= budget_chars:
            selected.add(line.line_id)

    packed = _render_selected(parsed, selected)
    packed_lines = [line for line in parsed if line.line_id in selected]
    return _pack_result(
        source=source,
        packed=packed,
        source_lines=source_lines,
        packed_lines=packed_lines,
        budget_chars=budget_chars,
    )


def _clean_context(memory_context: str) -> str:
    return "\n".join(
        line.rstrip() for line in (memory_context or "").splitlines()
    ).strip()


def _parse_lines(lines: list[str]) -> list[_MemoryLine]:
    parsed: list[_MemoryLine] = []
    section: str | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if _SECTION_RE.match(stripped):
            section = stripped
            continue
        if not stripped:
            continue
        parsed.append(
            _MemoryLine(
                line_id=index,
                section=section,
                text=line,
                priority=_line_priority(stripped, section),
            )
        )
    return parsed


def _line_priority(line: str, section: str | None) -> int:
    if _CURRENT_RE.search(line):
        return 1
    if section == "[ALWAYS KNOWN]":
        return 2
    if _NEEDS_REFRESH_RE.search(line):
        return 4
    if _HISTORICAL_RE.search(line):
        return 5
    return 3


def _render_selected(lines: list[_MemoryLine], selected: set[int]) -> str:
    parts: list[str] = []
    active_section: str | None = None
    for line in lines:
        if line.line_id not in selected:
            continue
        if line.section and line.section != active_section:
            if parts:
                parts.append("")
            parts.append(line.section)
            active_section = line.section
        parts.append(line.text)
    return "\n".join(parts).strip()


def _section_order(lines: list[_MemoryLine]) -> tuple[str, ...]:
    sections: list[str] = []
    for line in lines:
        if line.section and line.section not in sections:
            sections.append(line.section)
    return tuple(sections)


def _pack_result(
    *,
    source: str,
    packed: str,
    source_lines: list[str],
    packed_lines: list[_MemoryLine],
    budget_chars: int,
) -> ChatMemoryPack:
    parsed_source_lines = _parse_lines(source_lines)
    packed_ids = {line.line_id for line in packed_lines}
    return ChatMemoryPack(
        context=packed,
        manifest=ChatMemoryPackManifest(
            source_chars=len(source),
            packed_chars=len(packed),
            budget_chars=budget_chars,
            source_line_count=len(parsed_source_lines),
            packed_line_count=len(packed_lines),
            dropped_line_count=max(0, len(parsed_source_lines) - len(packed_ids)),
            section_order=_section_order(packed_lines),
            current_line_count=sum(
                1 for line in packed_lines if _CURRENT_RE.search(line.text)
            ),
            historical_line_count=sum(
                1 for line in packed_lines if _HISTORICAL_RE.search(line.text)
            ),
            needs_refresh_line_count=sum(
                1 for line in packed_lines if _NEEDS_REFRESH_RE.search(line.text)
            ),
            truncated=bool(source and packed != source),
        ),
    )
