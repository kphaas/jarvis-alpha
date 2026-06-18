"""Obsidian-backed note and task skills.

The vault path is configuration, not source code. Production reads it from
``OBSIDIAN_VAULT_PATH``; tests may inject ``_vault_root`` in the skill payload.
"""

from __future__ import annotations

import fcntl
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from brain.config.secrets import get_secret
from brain.skills.runner import SkillCall

MAX_SEARCH_RESULTS = 50
MAX_NOTE_BYTES = 512 * 1024
MAX_DIGEST_BODY_CHARS = 50_000
MAX_SEARCH_FILES = 5000
DEFAULT_TASKS_INBOX = "Inbox.md"
DEFAULT_PRIVATE_DIGEST_DIR = "AT-0/Private Document Digests"
TASK_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
TAG_RE = re.compile(r"^#?[A-Za-z0-9_/-]{1,80}$")
NOTE_DIGEST_ID_RE = TASK_ID_RE
IGNORED_DIRS = {
    ".git",
    ".obsidian",
    ".trash",
    ".jarvis",
    ".sync",
    "node_modules",
    "__pycache__",
}
DUE_MARKER = "\U0001f4c5"
SCHEDULED_MARKER = "\u23f3"
PRIORITY_MARKERS = {
    "low": "\U0001f53d",
    "normal": "",
    "high": "\U0001f53c",
    "highest": "\u23eb",
}


class ObsidianSkillError(RuntimeError):
    """Raised when an Obsidian skill cannot safely complete."""


class NotesSearchPayload(BaseModel):
    query: str = Field(min_length=2, max_length=120)
    max_results: int = Field(default=10, ge=1, le=MAX_SEARCH_RESULTS)
    path_prefix: str | None = Field(default=None, max_length=240)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("query must contain at least two searchable characters")
        return normalized


class TasksCreatePayload(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    due: date | None = None
    scheduled: date | None = None
    tags: list[str] = Field(default_factory=list, max_length=12)
    path: str | None = Field(default=None, max_length=240)
    priority: str = Field(default="normal", pattern="^(low|normal|high|highest)$")

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("title must be non-empty")
        if any(token in value for token in ("\n", "\r", "\x00", "<!--")):
            raise ValueError("title contains unsupported markdown control text")
        return normalized

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        tags: list[str] = []
        for raw_tag in value:
            tag = raw_tag.strip()
            if not tag:
                continue
            if not TAG_RE.match(tag):
                raise ValueError(f"invalid task tag: {raw_tag}")
            tags.append(tag if tag.startswith("#") else f"#{tag}")
        return sorted(set(tags))


class NotesWritePrivateDigestPayload(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    body: str = Field(min_length=1, max_length=MAX_DIGEST_BODY_CHARS)
    tags: list[str] = Field(default_factory=list, max_length=12)
    path: str | None = Field(default=None, max_length=240)
    document_id: str | None = Field(default=None, max_length=120)
    source_name: str | None = Field(default=None, max_length=240)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("title must be non-empty")
        if any(token in value for token in ("\n", "\r", "\x00", "<!--")):
            raise ValueError("title contains unsupported markdown control text")
        return normalized

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("body contains unsupported control text")
        normalized = value.strip()
        if not normalized:
            raise ValueError("body must be non-empty")
        return normalized

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        tags: list[str] = []
        for raw_tag in value:
            tag = raw_tag.strip()
            if not tag:
                continue
            if not TAG_RE.match(tag):
                raise ValueError(f"invalid note tag: {raw_tag}")
            tags.append(tag.lstrip("#"))
        return sorted(set(tags))


async def notes_search(call: SkillCall) -> dict[str, Any]:
    payload = NotesSearchPayload.model_validate(_public_payload(call))
    root = _vault_root(call.payload)
    search_root = _safe_dir(root, payload.path_prefix)
    query = payload.query.casefold()

    matches: list[dict[str, Any]] = []
    files_seen = 0
    for note_path in _iter_markdown_files(search_root):
        files_seen += 1
        if files_seen > MAX_SEARCH_FILES:
            break
        rel_path = note_path.relative_to(root).as_posix()
        filename_score = 5 if query in note_path.stem.casefold() else 0
        try:
            if note_path.stat().st_size > MAX_NOTE_BYTES:
                continue
            text = note_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for line_number, line in enumerate(text.splitlines(), start=1):
            line_match = query in line.casefold()
            if filename_score or line_match:
                matches.append(
                    {
                        "path": rel_path,
                        "title": note_path.stem,
                        "line_number": line_number,
                        "excerpt": _excerpt(line, payload.query),
                        "score": filename_score + (1 if line_match else 0),
                    }
                )
                break

    matches.sort(
        key=lambda item: (-int(item["score"]), item["path"], item["line_number"])
    )
    limited = matches[: payload.max_results]
    return {
        "status": "ok",
        "query": payload.query,
        "count": len(limited),
        "truncated": len(matches) > len(limited) or files_seen > MAX_SEARCH_FILES,
        "results": limited,
    }


async def notes_write_private_digest(call: SkillCall) -> dict[str, Any]:
    idempotency_key = call.invocation.idempotency_key
    if not idempotency_key or not NOTE_DIGEST_ID_RE.match(idempotency_key):
        raise ObsidianSkillError("valid_idempotency_key_required")

    payload = NotesWritePrivateDigestPayload.model_validate(_public_payload(call))
    root = _vault_root(call.payload)
    target = _safe_markdown_file(
        root,
        payload.path or _default_private_digest_path(payload.title),
    )
    marker = _note_marker(idempotency_key)
    note_text = _private_digest_markdown(payload, idempotency_key)

    created = False
    lock_path = _lock_path(root)
    with lock_path.open("a", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            if marker in existing:
                status = "exists"
            elif existing.strip():
                raise ObsidianSkillError("target_exists_without_digest_marker")
            else:
                _atomic_write_text(target, note_text)
                created = True
                status = "created"
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    return {
        "status": status,
        "created": created,
        "path": target.relative_to(root).as_posix(),
        "idempotency_key": idempotency_key,
        "marker": marker,
    }


async def tasks_create(call: SkillCall) -> dict[str, Any]:
    idempotency_key = call.invocation.idempotency_key
    if not idempotency_key or not TASK_ID_RE.match(idempotency_key):
        raise ObsidianSkillError("valid_idempotency_key_required")

    payload = TasksCreatePayload.model_validate(_public_payload(call))
    root = _vault_root(call.payload)
    target = _safe_markdown_file(
        root,
        payload.path or _default_tasks_inbox(),
    )
    task_line = _task_line(payload, idempotency_key)
    marker = _task_marker(idempotency_key)

    created = False
    lock_path = _lock_path(root)
    with lock_path.open("a", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            if marker not in existing:
                _atomic_write_text(target, _append_line(existing, task_line))
                created = True
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    return {
        "status": "created" if created else "exists",
        "path": target.relative_to(root).as_posix(),
        "idempotency_key": idempotency_key,
        "line": task_line,
    }


def obsidian_skill_handlers() -> dict[str, Any]:
    return {
        "notes.search": notes_search,
        "notes.write_private_digest": notes_write_private_digest,
        "tasks.create": tasks_create,
    }


def _public_payload(call: SkillCall) -> dict[str, Any]:
    return {
        key: value for key, value in call.payload.items() if not key.startswith("_")
    }


def _vault_root(payload: Any) -> Path:
    if isinstance(payload, dict) and payload.get("_vault_root") is not None:
        raw_path = str(payload["_vault_root"])
    else:
        try:
            raw_path = get_secret("OBSIDIAN_VAULT_PATH")
        except KeyError as exc:
            raise ObsidianSkillError("obsidian_vault_path_missing") from exc

    root = Path(raw_path).expanduser().resolve()
    if not root.exists():
        raise ObsidianSkillError("obsidian_vault_path_not_found")
    if not root.is_dir():
        raise ObsidianSkillError("obsidian_vault_path_not_directory")
    return root


def _default_tasks_inbox() -> str:
    try:
        return get_secret("OBSIDIAN_TASKS_INBOX")
    except KeyError:
        return DEFAULT_TASKS_INBOX


def _default_private_digest_path(title: str) -> str:
    return f"{DEFAULT_PRIVATE_DIGEST_DIR}/{_slugify(title)}.md"


def _safe_dir(root: Path, requested: str | None) -> Path:
    if not requested:
        return root
    target = _safe_path(root, requested)
    if target.exists() and not target.is_dir():
        raise ObsidianSkillError("path_prefix_not_directory")
    return target


def _safe_markdown_file(root: Path, requested: str) -> Path:
    target = _safe_path(root, requested)
    if target.suffix.lower() != ".md":
        raise ObsidianSkillError("target_must_be_markdown")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _safe_path(root: Path, requested: str) -> Path:
    raw = Path(requested)
    if raw.is_absolute():
        raise ObsidianSkillError("absolute_paths_not_allowed")
    if any(part in {"", ".", ".."} for part in raw.parts):
        raise ObsidianSkillError("unsafe_relative_path")
    if any(part in IGNORED_DIRS or part.startswith(".") for part in raw.parts):
        raise ObsidianSkillError("hidden_paths_not_allowed")
    target = (root / raw).resolve()
    if not (target == root or root in target.parents):
        raise ObsidianSkillError("path_escapes_vault")
    return target


def _iter_markdown_files(root: Path):
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in IGNORED_DIRS and not dirname.startswith(".")
        ]
        for filename in sorted(filenames):
            if filename.startswith(".") or not filename.lower().endswith(".md"):
                continue
            yield Path(current_root) / filename


def _excerpt(line: str, query: str) -> str:
    compact = " ".join(line.split())
    if len(compact) <= 240:
        return compact
    idx = compact.casefold().find(query.casefold())
    if idx < 0:
        return compact[:237] + "..."
    start = max(0, idx - 80)
    end = min(len(compact), idx + len(query) + 160)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(compact) else ""
    return f"{prefix}{compact[start:end]}{suffix}"


def _task_line(payload: TasksCreatePayload, idempotency_key: str) -> str:
    tokens = [f"- [ ] {payload.title}"]
    if payload.scheduled:
        tokens.append(f"{SCHEDULED_MARKER} {payload.scheduled.isoformat()}")
    if payload.due:
        tokens.append(f"{DUE_MARKER} {payload.due.isoformat()}")
    priority = PRIORITY_MARKERS[payload.priority]
    if priority:
        tokens.append(priority)
    tokens.extend(payload.tags)
    tokens.append(_task_marker(idempotency_key))
    return " ".join(tokens)


def _task_marker(idempotency_key: str) -> str:
    return f"<!-- jarvis-task-id:{idempotency_key} -->"


def _note_marker(idempotency_key: str) -> str:
    return f"<!-- jarvis-note-id:{idempotency_key} -->"


def _private_digest_markdown(
    payload: NotesWritePrivateDigestPayload,
    idempotency_key: str,
) -> str:
    tags = payload.tags or ["private"]
    lines = [
        "---",
        "private: true",
        'source: "alpha-vault-digest"',
        f'title: "{_yaml_escape(payload.title)}"',
    ]
    if payload.document_id:
        lines.append(f'document_id: "{_yaml_escape(payload.document_id)}"')
    if payload.source_name:
        lines.append(f'source_name: "{_yaml_escape(payload.source_name)}"')
    lines.append("tags:")
    lines.extend(f'  - "{_yaml_escape(tag)}"' for tag in tags)
    lines.extend(
        [
            "---",
            "",
            f"# {payload.title}",
            "",
            payload.body.strip(),
            "",
            _note_marker(idempotency_key),
            "",
        ]
    )
    return "\n".join(lines)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:80] or "document-digest"


def _yaml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _append_line(existing: str, line: str) -> str:
    if not existing:
        return line + "\n"
    separator = "" if existing.endswith("\n") else "\n"
    return f"{existing}{separator}{line}\n"


def _atomic_write_text(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_name = tmp.name
    try:
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _lock_path(root: Path) -> Path:
    lock_dir = root / ".jarvis"
    lock_dir.mkdir(mode=0o700, exist_ok=True)
    return lock_dir / "tasks.lock"
