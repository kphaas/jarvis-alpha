"""Phase 1 local workspace backend for governed Alpha agent runs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable
from uuid import UUID, uuid4

from brain.core.config import (
    ALPHA_AGENTFS_MAX_ARTIFACT_BYTES,
    ALPHA_AGENTFS_MAX_WORKSPACE_BYTES,
    ALPHA_AGENTFS_PREVIEW_BYTES,
    ALPHA_AGENT_WORKSPACE_ROOT,
)

WORKSPACE_BACKEND = "local"
_ARTIFACT_DIRS = frozenset({"input", "working", "outputs"})
_LOG_RELATIVE_PATH = "logs/events.jsonl"
_KIND_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_STREAM_CHUNK_BYTES = 64 * 1024
_DEFAULT_RETENTION_CLASS = "standard"
_RETENTION_WINDOWS = {
    "ephemeral": timedelta(hours=24),
    "standard": timedelta(days=7),
    "extended": timedelta(days=30),
    "archive": timedelta(days=90),
}


class WorkspacePathError(ValueError):
    """Raised when a requested workspace path escapes the allowed root."""


class WorkspaceRetentionExpiredError(ValueError):
    """Raised when a workspace has passed its retention window."""


@dataclass(frozen=True, slots=True)
class WorkspaceManifest:
    run_id: str
    agent_id: str
    created_at: str
    workspace_backend: str
    workspace_root: str
    policy_labels: tuple[str, ...]
    approval_scope: str | None
    retention_class: str

    def to_document(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "created_at": self.created_at,
            "workspace_backend": self.workspace_backend,
            "policy_labels": list(self.policy_labels),
            "approval_scope": self.approval_scope,
            "retention_class": self.retention_class,
        }

    def to_dict(self) -> dict[str, object]:
        document = self.to_document()
        document["workspace_root"] = self.workspace_root
        return document


@dataclass(frozen=True, slots=True)
class WorkspaceArtifactRecord:
    artifact_id: str
    run_id: str
    relative_path: str
    kind: str
    content_type: str
    size_bytes: int
    created_at: str
    sha256: str | None
    policy_labels: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "relative_path": self.relative_path,
            "kind": self.kind,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "sha256": self.sha256,
            "policy_labels": list(self.policy_labels),
        }


@dataclass(frozen=True, slots=True)
class StagedWorkspaceArtifact:
    record: WorkspaceArtifactRecord
    workspace_root: Path
    absolute_path: Path
    data: bytes | None = None
    staged_path: Path | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceArtifactPreview:
    text: str | None
    truncated: bool
    preview_bytes: int
    preview_available: bool


class LocalWorkspaceBackend:
    """Filesystem-backed workspace implementation with strict root guards."""

    def __init__(
        self,
        base_root: str | Path | None = None,
        *,
        max_artifact_bytes: int | None = None,
        max_workspace_bytes: int | None = None,
        preview_bytes: int | None = None,
    ) -> None:
        raw_root = base_root or ALPHA_AGENT_WORKSPACE_ROOT
        self.base_root = Path(raw_root).expanduser().resolve()
        self.max_artifact_bytes = max_artifact_bytes or ALPHA_AGENTFS_MAX_ARTIFACT_BYTES
        self.max_workspace_bytes = (
            max_workspace_bytes or ALPHA_AGENTFS_MAX_WORKSPACE_BYTES
        )
        self.preview_bytes = preview_bytes or ALPHA_AGENTFS_PREVIEW_BYTES

    def workspace_root(self, run_id: UUID | str) -> str:
        return str(self._default_workspace_root(run_id))

    def workspace_uri(self, run_id: UUID | str) -> str:
        return f"agentfs://runs/{run_id}"

    def retention_expires_at(
        self,
        created_at: datetime | str | None,
        retention_class: str,
    ) -> str:
        created = _coerce_datetime(created_at)
        return (created + _retention_window(retention_class)).isoformat()

    def workspace_state(
        self,
        *,
        created_at: datetime | str | None,
        retention_class: str,
        workspace_initialized: bool,
        now: datetime | None = None,
    ) -> str:
        if not workspace_initialized:
            return "not_initialized"
        if self.workspace_expired(
            created_at=created_at,
            retention_class=retention_class,
            now=now,
        ):
            return "expired"
        return "ready"

    def workspace_expired(
        self,
        *,
        created_at: datetime | str | None,
        retention_class: str,
        now: datetime | None = None,
    ) -> bool:
        current = now or datetime.now(tz=UTC)
        return current >= _coerce_datetime(
            self.retention_expires_at(created_at, retention_class)
        )

    def assert_within_retention(
        self,
        *,
        created_at: datetime | str | None,
        retention_class: str,
    ) -> None:
        if self.workspace_expired(
            created_at=created_at,
            retention_class=retention_class,
        ):
            raise WorkspaceRetentionExpiredError(
                "workspace retention expired; raw artifact access is disabled"
            )

    def init_workspace(
        self,
        run_id: UUID | str,
        agent_id: str,
        policy_labels: Iterable[str],
        approval_scope: str | None,
        retention_class: str,
        *,
        workspace_root: str | None = None,
        created_at: datetime | str | None = None,
    ) -> WorkspaceManifest:
        root = self._resolve_workspace_root(run_id, workspace_root)
        root.mkdir(parents=True, exist_ok=True)
        for dirname in ("input", "working", "outputs", "logs"):
            (root / dirname).mkdir(exist_ok=True)
        (root / "artifacts.jsonl").touch(exist_ok=True)

        manifest = WorkspaceManifest(
            run_id=str(run_id),
            agent_id=agent_id,
            created_at=_isoformat(created_at),
            workspace_backend=WORKSPACE_BACKEND,
            workspace_root=str(root),
            policy_labels=_normalize_labels(policy_labels),
            approval_scope=_clean_optional_text(approval_scope),
            retention_class=_clean_required_text(
                retention_class, field_name="retention_class"
            ),
        )
        (root / "manifest.json").write_text(
            json.dumps(manifest.to_document(), indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest

    def read_manifest(
        self,
        run_id: UUID | str,
        *,
        workspace_root: str | None = None,
    ) -> WorkspaceManifest:
        root = self._resolve_workspace_root(run_id, workspace_root)
        manifest_path = root / "manifest.json"
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        return WorkspaceManifest(
            run_id=str(document["run_id"]),
            agent_id=str(document["agent_id"]),
            created_at=str(document["created_at"]),
            workspace_backend=str(document["workspace_backend"]),
            workspace_root=str(root),
            policy_labels=_normalize_labels(document.get("policy_labels", [])),
            approval_scope=_clean_optional_text(document.get("approval_scope")),
            retention_class=_clean_required_text(
                document.get("retention_class"),
                field_name="retention_class",
            ),
        )

    def read_text(
        self,
        run_id: UUID | str,
        relative_path: str,
        *,
        workspace_root: str | None = None,
    ) -> str:
        return self.read_bytes(
            run_id,
            relative_path,
            workspace_root=workspace_root,
        ).decode("utf-8")

    def read_bytes(
        self,
        run_id: UUID | str,
        relative_path: str,
        *,
        workspace_root: str | None = None,
    ) -> bytes:
        return self.resolve_read_path(
            run_id,
            relative_path,
            workspace_root=workspace_root,
        ).read_bytes()

    def resolve_read_path(
        self,
        run_id: UUID | str,
        relative_path: str,
        *,
        workspace_root: str | None = None,
    ) -> Path:
        root = self._resolve_workspace_root(run_id, workspace_root)
        return self._resolve_read_path(root, relative_path)

    def workspace_usage_bytes(
        self,
        run_id: UUID | str,
        *,
        workspace_root: str | None = None,
    ) -> int:
        return sum(
            record.size_bytes
            for record in self.list_artifacts(run_id, workspace_root=workspace_root)
        )

    def preview_text(
        self,
        run_id: UUID | str,
        relative_path: str,
        *,
        workspace_root: str | None = None,
    ) -> WorkspaceArtifactPreview:
        path = self.resolve_read_path(
            run_id,
            relative_path,
            workspace_root=workspace_root,
        )
        with path.open("rb") as handle:
            payload = handle.read(self.preview_bytes + 1)
        truncated = len(payload) > self.preview_bytes
        if truncated:
            payload = payload[: self.preview_bytes]
        return WorkspaceArtifactPreview(
            text=payload.decode("utf-8", errors="replace").replace("\x00", "\ufffd"),
            truncated=truncated,
            preview_bytes=len(payload),
            preview_available=True,
        )

    def stage_text(
        self,
        run_id: UUID | str,
        relative_path: str,
        text: str,
        kind: str,
        *,
        content_type: str = "text/plain",
        policy_labels: Iterable[str] = (),
        workspace_root: str | None = None,
    ) -> StagedWorkspaceArtifact:
        return self.stage_bytes(
            run_id,
            relative_path,
            text.encode("utf-8"),
            kind,
            content_type=content_type or "text/plain",
            policy_labels=policy_labels,
            workspace_root=workspace_root,
        )

    def stage_bytes(
        self,
        run_id: UUID | str,
        relative_path: str,
        data: bytes,
        kind: str,
        *,
        content_type: str,
        policy_labels: Iterable[str] = (),
        workspace_root: str | None = None,
    ) -> StagedWorkspaceArtifact:
        root = self._resolve_workspace_root(run_id, workspace_root)
        target = self._resolve_artifact_path(root, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            # ponytail: phase 1 keeps artifact paths immutable; version a new path instead.
            raise WorkspacePathError("artifact path already exists")
        self._assert_workspace_capacity(
            run_id,
            incoming_size=len(data),
            workspace_root=workspace_root,
        )
        record = WorkspaceArtifactRecord(
            artifact_id=str(uuid4()),
            run_id=str(run_id),
            relative_path=relative_path,
            kind=_normalize_kind(kind),
            content_type=_clean_required_text(content_type, field_name="content_type"),
            size_bytes=len(data),
            created_at=_isoformat(None),
            sha256=hashlib.sha256(data).hexdigest(),
            policy_labels=_normalize_labels(policy_labels),
        )
        return StagedWorkspaceArtifact(
            record=record,
            workspace_root=root,
            absolute_path=target,
            data=data,
        )

    def stage_upload_stream(
        self,
        run_id: UUID | str,
        relative_path: str,
        stream: BinaryIO,
        kind: str,
        *,
        content_type: str,
        policy_labels: Iterable[str] = (),
        workspace_root: str | None = None,
    ) -> StagedWorkspaceArtifact:
        root = self._resolve_workspace_root(run_id, workspace_root)
        target = self._resolve_artifact_path(root, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise WorkspacePathError("artifact path already exists")
        current_usage = self.workspace_usage_bytes(
            run_id, workspace_root=workspace_root
        )
        staged_path = target.with_name(f".{target.name}.{uuid4().hex}.upload")
        sha256 = hashlib.sha256()
        size_bytes = 0
        try:
            with staged_path.open("wb") as handle:
                while True:
                    chunk = stream.read(_STREAM_CHUNK_BYTES)
                    if not chunk:
                        break
                    size_bytes += len(chunk)
                    self._assert_capacity(
                        incoming_size=size_bytes,
                        current_usage=current_usage,
                    )
                    sha256.update(chunk)
                    handle.write(chunk)
        except Exception:
            try:
                staged_path.unlink()
            except FileNotFoundError:
                pass
            raise
        record = WorkspaceArtifactRecord(
            artifact_id=str(uuid4()),
            run_id=str(run_id),
            relative_path=relative_path,
            kind=_normalize_kind(kind),
            content_type=_clean_required_text(content_type, field_name="content_type"),
            size_bytes=size_bytes,
            created_at=_isoformat(None),
            sha256=sha256.hexdigest(),
            policy_labels=_normalize_labels(policy_labels),
        )
        return StagedWorkspaceArtifact(
            record=record,
            workspace_root=root,
            absolute_path=target,
            staged_path=staged_path,
        )

    def commit_staged_artifact(
        self,
        staged: StagedWorkspaceArtifact,
    ) -> WorkspaceArtifactRecord:
        if staged.staged_path is not None:
            staged.staged_path.replace(staged.absolute_path)
        else:
            staged.absolute_path.write_bytes(staged.data or b"")
        self._append_artifact_ledger(staged.workspace_root, staged.record)
        return staged.record

    def cleanup_staged_artifact(self, staged: StagedWorkspaceArtifact) -> None:
        for candidate in (staged.staged_path, staged.absolute_path):
            if candidate is None:
                continue
            try:
                candidate.unlink()
            except FileNotFoundError:
                continue

    def write_text(
        self,
        run_id: UUID | str,
        relative_path: str,
        text: str,
        kind: str,
        *,
        content_type: str = "text/plain",
        policy_labels: Iterable[str] = (),
        workspace_root: str | None = None,
    ) -> WorkspaceArtifactRecord:
        staged = self.stage_text(
            run_id,
            relative_path,
            text,
            kind,
            content_type=content_type,
            policy_labels=policy_labels,
            workspace_root=workspace_root,
        )
        return self.commit_staged_artifact(staged)

    def write_bytes(
        self,
        run_id: UUID | str,
        relative_path: str,
        data: bytes,
        kind: str,
        *,
        content_type: str,
        policy_labels: Iterable[str] = (),
        workspace_root: str | None = None,
    ) -> WorkspaceArtifactRecord:
        staged = self.stage_bytes(
            run_id,
            relative_path,
            data,
            kind,
            content_type=content_type,
            policy_labels=policy_labels,
            workspace_root=workspace_root,
        )
        return self.commit_staged_artifact(staged)

    def append_log(
        self,
        run_id: UUID | str,
        event_type: str,
        payload: dict[str, object],
        *,
        policy_labels: Iterable[str] = (),
        workspace_root: str | None = None,
    ) -> WorkspaceArtifactRecord:
        root = self._resolve_workspace_root(run_id, workspace_root)
        log_path = root / _LOG_RELATIVE_PATH
        log_path.parent.mkdir(parents=True, exist_ok=True)
        created_at = _isoformat(None)
        line = json.dumps(
            {
                "event_type": _normalize_kind(event_type),
                "payload": payload,
                "created_at": created_at,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        record = WorkspaceArtifactRecord(
            artifact_id=str(uuid4()),
            run_id=str(run_id),
            relative_path=_LOG_RELATIVE_PATH,
            kind=f"log.{_normalize_kind(event_type)}",
            content_type="application/json",
            size_bytes=len((line + "\n").encode("utf-8")),
            created_at=created_at,
            sha256=hashlib.sha256((line + "\n").encode("utf-8")).hexdigest(),
            policy_labels=_normalize_labels(policy_labels),
        )
        self._append_artifact_ledger(root, record)
        return record

    def list_artifacts(
        self,
        run_id: UUID | str,
        *,
        workspace_root: str | None = None,
    ) -> list[WorkspaceArtifactRecord]:
        root = self._resolve_workspace_root(run_id, workspace_root)
        ledger_path = root / "artifacts.jsonl"
        if not ledger_path.exists():
            return []
        records: list[WorkspaceArtifactRecord] = []
        with ledger_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                item = json.loads(line)
                records.append(
                    WorkspaceArtifactRecord(
                        artifact_id=str(item["artifact_id"]),
                        run_id=str(item["run_id"]),
                        relative_path=str(item["relative_path"]),
                        kind=str(item["kind"]),
                        content_type=str(item["content_type"]),
                        size_bytes=int(item["size_bytes"]),
                        created_at=str(item["created_at"]),
                        sha256=str(item["sha256"]) if item.get("sha256") else None,
                        policy_labels=_normalize_labels(item.get("policy_labels", [])),
                    )
                )
        return records

    def _assert_workspace_capacity(
        self,
        run_id: UUID | str,
        *,
        incoming_size: int,
        workspace_root: str | None = None,
    ) -> None:
        self._assert_capacity(
            incoming_size=incoming_size,
            current_usage=self.workspace_usage_bytes(
                run_id,
                workspace_root=workspace_root,
            ),
        )

    def _assert_capacity(self, *, incoming_size: int, current_usage: int) -> None:
        if incoming_size > self.max_artifact_bytes:
            raise ValueError(
                f"artifact exceeds max size ({self.max_artifact_bytes} bytes max)"
            )
        if current_usage + incoming_size > self.max_workspace_bytes:
            raise ValueError(
                f"workspace quota exceeded ({self.max_workspace_bytes} bytes max)"
            )

    def _append_artifact_ledger(
        self,
        workspace_root: Path,
        record: WorkspaceArtifactRecord,
    ) -> None:
        ledger_path = workspace_root / "artifacts.jsonl"
        with ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), separators=(",", ":")) + "\n")

    def _resolve_workspace_root(
        self,
        run_id: UUID | str,
        workspace_root: str | None,
    ) -> Path:
        root = (
            Path(workspace_root).expanduser().resolve()
            if workspace_root and workspace_root.strip()
            else self._default_workspace_root(run_id)
        )
        try:
            root.relative_to(self.base_root)
        except ValueError as exc:
            raise WorkspacePathError(
                "workspace_root must stay under the configured base directory"
            ) from exc
        if root.exists() and not root.is_dir():
            raise WorkspacePathError("workspace_root is not a directory")
        return root

    def _default_workspace_root(self, run_id: UUID | str) -> Path:
        return (self.base_root / str(run_id)).resolve()

    def _resolve_artifact_path(self, workspace_root: Path, relative_path: str) -> Path:
        normalized = self._normalize_artifact_path(relative_path)
        target = (workspace_root / Path(*normalized.parts)).resolve()
        try:
            target.relative_to(workspace_root)
        except ValueError as exc:
            raise WorkspacePathError(
                "relative_path must stay under workspace_root"
            ) from exc
        return target

    def _resolve_read_path(self, workspace_root: Path, relative_path: str) -> Path:
        clean = relative_path.replace("\\", "/").strip()
        if not clean:
            raise WorkspacePathError("relative_path must be non-empty")
        normalized = PurePosixPath(clean)
        if normalized.is_absolute() or any(
            part in {"", ".", ".."} for part in normalized.parts
        ):
            raise WorkspacePathError("relative_path must stay under workspace_root")
        target = (workspace_root / Path(*normalized.parts)).resolve()
        try:
            target.relative_to(workspace_root)
        except ValueError as exc:
            raise WorkspacePathError(
                "relative_path must stay under workspace_root"
            ) from exc
        return target

    def _normalize_artifact_path(self, relative_path: str) -> PurePosixPath:
        clean = relative_path.replace("\\", "/").strip()
        if not clean:
            raise WorkspacePathError("relative_path must be non-empty")
        normalized = PurePosixPath(clean)
        if normalized.is_absolute() or any(
            part in {"", ".", ".."} for part in normalized.parts
        ):
            raise WorkspacePathError("relative_path must stay under workspace_root")
        if normalized.parts[0] not in _ARTIFACT_DIRS:
            raise WorkspacePathError(
                "relative_path must start with input/, working/, or outputs/"
            )
        return normalized


def get_workspace_backend() -> LocalWorkspaceBackend:
    return LocalWorkspaceBackend()


def _normalize_labels(policy_labels: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in policy_labels:
        value = str(raw).strip()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return tuple(normalized)


def _normalize_kind(kind: str) -> str:
    value = _clean_required_text(kind, field_name="kind")
    if not _KIND_RE.match(value):
        raise ValueError("kind must match ^[a-z][a-z0-9_.-]{0,79}$")
    return value


def _clean_required_text(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty")
    return text


def _clean_optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _retention_window(retention_class: str) -> timedelta:
    clean = _clean_optional_text(retention_class) or _DEFAULT_RETENTION_CLASS
    return _RETENTION_WINDOWS.get(clean, _RETENTION_WINDOWS[_DEFAULT_RETENTION_CLASS])


def _coerce_datetime(value: datetime | str | None) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return datetime.now(tz=UTC)


def _isoformat(value: datetime | str | None) -> str:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    return datetime.now(tz=UTC).isoformat()
