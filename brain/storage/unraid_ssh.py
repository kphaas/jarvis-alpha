from __future__ import annotations

import os
import posixpath
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

DEFAULT_UNRAID_DOCUMENT_ROOT = "/mnt/user/Documents"
DEFAULT_TIMEOUT_SECONDS = 120


class UnraidSshArchiveError(RuntimeError):
    """Raised when Alpha cannot mirror a staged document to Unraid over SSH."""


@dataclass(frozen=True)
class UnraidSshConfig:
    host: str
    user: str
    key_path: str
    root: str
    timeout_seconds: int


def _candidate_secret_files() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("SECRETS_FILE")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.append(Path.home() / "jarvis" / ".secrets")
    candidates.append(Path.home() / ".secrets")
    return candidates


def _file_secret(key: str) -> str | None:
    for path in _candidate_secret_files():
        if not path.is_file():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                candidate_key, value = stripped.split("=", 1)
                if candidate_key.strip() == key and value.strip():
                    return value.strip()
    return None


def _secret_value(key: str) -> str | None:
    env_value = os.environ.get(key)
    if env_value and env_value.strip():
        return env_value.strip()
    return _file_secret(key)


def _config_value(
    primary_key: str,
    *,
    fallback_key: str | None = None,
    default: str | None = None,
) -> str:
    for key in (primary_key, fallback_key):
        if key is None:
            continue
        value = _secret_value(key)
        if value is not None:
            return value
    if default is not None:
        return default
    raise UnraidSshArchiveError(f"missing required Unraid SSH config: {primary_key}")


def _timeout_seconds() -> int:
    raw = os.environ.get("ALPHA_UNRAID_SSH_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = int(raw)
    except ValueError as exc:
        raise UnraidSshArchiveError(
            "ALPHA_UNRAID_SSH_TIMEOUT_SECONDS must be an integer"
        ) from exc
    if timeout <= 0:
        raise UnraidSshArchiveError("ALPHA_UNRAID_SSH_TIMEOUT_SECONDS must be positive")
    return timeout


def load_unraid_ssh_config() -> UnraidSshConfig:
    """
    Load the document archive SSH config.

    Alpha backup already owns the working Brain -> Unraid SSH route. The
    document-specific keys allow future separation, while the BACKUP_SSH_*
    fallback keeps today's vault pipeline aligned with the proven transport.
    """

    return UnraidSshConfig(
        host=_config_value("ALPHA_UNRAID_SSH_HOST", fallback_key="BACKUP_SSH_HOST"),
        user=_config_value("ALPHA_UNRAID_SSH_USER", fallback_key="BACKUP_SSH_USER"),
        key_path=_config_value("ALPHA_UNRAID_SSH_KEY", fallback_key="BACKUP_SSH_KEY"),
        root=_config_value(
            "ALPHA_UNRAID_SSH_ROOT",
            default=DEFAULT_UNRAID_DOCUMENT_ROOT,
        ).rstrip("/"),
        timeout_seconds=_timeout_seconds(),
    )


def _target(config: UnraidSshConfig) -> str:
    return f"{config.user}@{config.host}"


def _ssh_args(config: UnraidSshConfig) -> list[str]:
    return [
        "ssh",
        "-n",
        "-i",
        config.key_path,
        "-o",
        "BatchMode=yes",
        "-o",
        "NumberOfPasswordPrompts=0",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"ConnectTimeout={min(config.timeout_seconds, 30)}",
        _target(config),
    ]


def _scp_args(config: UnraidSshConfig) -> list[str]:
    return [
        "scp",
        "-i",
        config.key_path,
        "-o",
        "BatchMode=yes",
        "-o",
        "NumberOfPasswordPrompts=0",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        f"ConnectTimeout={min(config.timeout_seconds, 30)}",
        "-q",
    ]


def _run(
    args: Sequence[str],
    *,
    timeout_seconds: int,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        list(args),
        input=input_bytes,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        detail = stderr or f"command exited {result.returncode}"
        raise UnraidSshArchiveError(detail)
    return result


def _remote_path(config: UnraidSshConfig, folder: str, archive_name: str) -> str:
    return posixpath.join(config.root, folder, archive_name)


def mirror_file_to_unraid_ssh(
    *,
    src_path: str,
    folder: str,
    archive_name: str,
    sha256: str,
) -> dict[str, str]:
    config = load_unraid_ssh_config()
    src = Path(src_path)
    if not src.is_file():
        raise UnraidSshArchiveError(f"source file not found: {src_path}")

    remote_dir = posixpath.join(config.root, folder)
    remote_path = _remote_path(config, folder, archive_name)
    remote_partial = f"{remote_path}.partial"

    mkdir_cmd = f"mkdir -p {remote_dir!r}"
    _run([*_ssh_args(config), mkdir_cmd], timeout_seconds=config.timeout_seconds)

    _run(
        [*_scp_args(config), str(src), f"{_target(config)}:{remote_partial}"],
        timeout_seconds=config.timeout_seconds,
    )

    verify_cmd = (
        f"chmod 600 {remote_partial!r} && "
        f"sha256sum {remote_partial!r} | awk '{{print $1}}'"
    )
    verify_result = _run(
        [*_ssh_args(config), verify_cmd],
        timeout_seconds=config.timeout_seconds,
    )
    remote_sha = (
        verify_result.stdout.decode("utf-8", errors="replace").strip().splitlines()[0]
    )
    if remote_sha != sha256:
        cleanup_cmd = f"rm -f {remote_partial!r}"
        _run([*_ssh_args(config), cleanup_cmd], timeout_seconds=config.timeout_seconds)
        raise UnraidSshArchiveError("remote sha256 mismatch after Unraid transfer")

    mv_cmd = f"mv -f {remote_partial!r} {remote_path!r}"
    _run([*_ssh_args(config), mv_cmd], timeout_seconds=config.timeout_seconds)

    return {
        "archive_path": f"unraid:{remote_path}",
        "remote_path": remote_path,
        "transport": "ssh",
        "mirrored_at": datetime.now(timezone.utc).isoformat(),
    }
