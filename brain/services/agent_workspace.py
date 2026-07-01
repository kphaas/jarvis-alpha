"""Phase 1 local workspace backend for governed Alpha agent runs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Iterable
from uuid import UUID, uuid4

from brain.core.config import ALPHA_AGENT_WORKSPACE_ROOT

WORKSPACE_BACKEND = "local"
_ARTIFACT_DIRS = frozenset({"input", "working", "outputs"})
_LOG_RELATIVE_PATH = "logs/events.jsonl"
_KIND_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")


class WorkspacePathError(ValueError):
    """Raised when a requested workspace path escapes the allowed root."""


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
    data: bytes


class LocalWorkspaceBackend:
    """Filesystem-backed workspace implementation with strict root guards."""

    def __init__(self, base_root: str | Path | None = None) -> None:
        raw_root = base_root or ALPHA_AGENT_WORKSPACE_ROOT
        self.base_root = Path(raw_root).expanduser().resolve()

    def workspace_root(self, run_id: UUID | str) -> str:
        return str(self._default_workspace_root(run_id))

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
        root = self._resolve_workspace_root(run_id, workspace_root)
        target = self._resolve_read_path(root, relative_path)
        return target.read_bytes()

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

    def commit_staged_artifact(
        self,
        staged: StagedWorkspaceArtifact,
    ) -> WorkspaceArtifactRecord:
        staged.absolute_path.write_bytes(staged.data)
        self._append_artifact_ledger(staged.workspace_root, staged.record)
        return staged.record

    def cleanup_staged_artifact(self, staged: StagedWorkspaceArtifact) -> None:
        try:
            staged.absolute_path.unlink()
        except FileNotFoundError:
            return

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


def _isoformat(value: datetime | str | None) -> str:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    return datetime.now(tz=UTC).isoformat()
