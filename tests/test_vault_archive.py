from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import brain.storage.archive as archive
import brain.storage.unraid_ssh as unraid_ssh


def _clear_unraid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ALPHA_UNRAID_SSH_HOST",
        "ALPHA_UNRAID_SSH_USER",
        "ALPHA_UNRAID_SSH_KEY",
        "ALPHA_UNRAID_SSH_ROOT",
        "BACKUP_SSH_HOST",
        "BACKUP_SSH_USER",
        "BACKUP_SSH_KEY",
        "ALPHA_UNRAID_SSH_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def alpha_inbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    inbox = tmp_path / "JarvisSecure" / "03_staging" / "inbox"
    monkeypatch.setattr(archive, "INBOX_PATH", str(inbox))
    return inbox


def test_unraid_ssh_config_uses_alpha_values_before_backup_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_unraid_env(monkeypatch)
    secrets = tmp_path / ".secrets"
    secrets.write_text(
        "\n".join(
            [
                "BACKUP_SSH_HOST=backup-host",
                "BACKUP_SSH_USER=backup-user",
                "BACKUP_SSH_KEY=/tmp/backup-key",
                "ALPHA_UNRAID_SSH_HOST=alpha-host",
                "ALPHA_UNRAID_SSH_USER=alpha-user",
                "ALPHA_UNRAID_SSH_KEY=/tmp/alpha-key",
                "ALPHA_UNRAID_SSH_ROOT=/mnt/user/Documents",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SECRETS_FILE", str(secrets))

    config = unraid_ssh.load_unraid_ssh_config()

    assert config.host == "alpha-host"
    assert config.user == "alpha-user"
    assert config.key_path == "/tmp/alpha-key"
    assert config.root == "/mnt/user/Documents"


def test_unraid_ssh_config_falls_back_to_backup_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_unraid_env(monkeypatch)
    secrets = tmp_path / ".secrets"
    secrets.write_text(
        "\n".join(
            [
                "BACKUP_SSH_HOST=backup-host",
                "BACKUP_SSH_USER=backup-user",
                "BACKUP_SSH_KEY=/tmp/backup-key",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SECRETS_FILE", str(secrets))

    config = unraid_ssh.load_unraid_ssh_config()

    assert config.host == "backup-host"
    assert config.user == "backup-user"
    assert config.key_path == "/tmp/backup-key"
    assert config.root == "/mnt/user/Documents"


@pytest.mark.asyncio
async def test_archive_document_mirrors_finance_to_unraid_ssh(
    tmp_path: Path,
    alpha_inbox: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "upload.tmp"
    source.write_bytes(b"tax return bytes")
    calls: list[dict[str, Any]] = []

    def fake_mirror(**kwargs: Any) -> dict[str, str]:
        calls.append(kwargs)
        assert Path(kwargs["src_path"]).read_bytes() == b"tax return bytes"
        return {
            "archive_path": f"unraid:/mnt/user/Documents/{kwargs['folder']}/{kwargs['archive_name']}",
            "remote_path": f"/mnt/user/Documents/{kwargs['folder']}/{kwargs['archive_name']}",
            "transport": "ssh",
        }

    monkeypatch.setattr(archive, "mirror_file_to_unraid_ssh", fake_mirror)

    result = await archive.archive_document(
        local_path=str(source),
        filename="2024 Return.pdf",
        classification="30_FINANCE",
        doc_id="doc-123",
    )

    assert "error" not in result
    assert result["tier"] == "unraid"
    assert (
        result["archive_path"]
        == "unraid:/mnt/user/Documents/30_FINANCE/doc-123_2024_Return.pdf"
    )
    assert (
        result["unraid_remote_path"]
        == "/mnt/user/Documents/30_FINANCE/doc-123_2024_Return.pdf"
    )
    assert result["archive_transport"] == "ssh"
    assert calls == [
        {
            "src_path": str(alpha_inbox / "doc-123_2024_Return.pdf"),
            "folder": "30_FINANCE",
            "archive_name": "doc-123_2024_Return.pdf",
            "sha256": result["sha256"],
        }
    ]
    assert not source.exists()
    assert (alpha_inbox / "doc-123_2024_Return.pdf").read_bytes() == b"tax return bytes"


@pytest.mark.asyncio
async def test_archive_document_returns_confirm_error_when_unraid_mirror_fails(
    tmp_path: Path,
    alpha_inbox: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "upload.tmp"
    source.write_bytes(b"tax return bytes")

    def fail_mirror(**_: Any) -> dict[str, str]:
        raise RuntimeError("ssh failed")

    monkeypatch.setattr(archive, "mirror_file_to_unraid_ssh", fail_mirror)

    result = await archive.archive_document(
        local_path=str(source),
        filename="tax.pdf",
        classification="30_FINANCE",
        doc_id="doc-456",
    )

    assert result["tier"] == "nvme_only"
    assert result["archive_path"] == str(alpha_inbox / "doc-456_tax.pdf")
    assert result["error"] == "ssh failed"
    assert not source.exists()
    assert (alpha_inbox / "doc-456_tax.pdf").read_bytes() == b"tax return bytes"


@pytest.mark.asyncio
async def test_archive_document_keeps_secrets_nvme_only(
    tmp_path: Path,
    alpha_inbox: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "upload.tmp"
    source.write_bytes(b"secret bytes")

    def fail_if_called(**_: Any) -> dict[str, str]:
        raise AssertionError("50_SECRETS must not mirror to Unraid")

    monkeypatch.setattr(archive, "mirror_file_to_unraid_ssh", fail_if_called)

    result = await archive.archive_document(
        local_path=str(source),
        filename="../secret.pdf",
        classification="50_SECRETS",
        doc_id="doc-789",
    )

    assert result["tier"] == "nvme_only"
    assert result["archive_path"] == str(alpha_inbox / "doc-789_secret.pdf")
    assert result["unraid_remote_path"] is None
    assert (alpha_inbox / "doc-789_secret.pdf").read_bytes() == b"secret bytes"
