import asyncio
import hashlib
import os as _os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from jarvis_common.logging_config import get_logger
from brain.storage.unraid_ssh import mirror_file_to_unraid_ssh

JARVIS_SECURE = _os.environ.get("ALPHA_NVME_PATH", "/Volumes/JarvisSecure")
INBOX_PATH = f"{JARVIS_SECURE}/03_staging/inbox"
_SAFE_ARCHIVE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

TIER_TO_UNRAID = {
    "10_PUBLIC": "10_PERSONAL",
    "20_PROJECTS": "20_FAMILY",
    "30_FINANCE": "30_FINANCE",
    "40_PRIVATE": "40_LEGAL",
    "50_SECRETS": None,
}

logger = get_logger("alpha_brain")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _move_sync(src: str, dst: str) -> None:
    shutil.move(src, dst)


def _archive_name(doc_id: str, filename: str) -> str:
    leaf = filename.replace("\\", "/").rsplit("/", 1)[-1].strip() or "document"
    safe_leaf = _SAFE_ARCHIVE_CHARS.sub("_", leaf).strip("._") or "document"
    return f"{doc_id}_{safe_leaf}"


async def archive_document(
    local_path: str,
    filename: str,
    classification: str,
    doc_id: str,
) -> dict:
    """
    Stage the file on JarvisSecure inbox, optionally mirror to Unraid by classification.

    Hashes before move, then moves into the inbox. For tiers mapped to Unraid,
    mirrors over the Brain -> Unraid SSH transport already used by Alpha
    backups. If Unraid mirroring fails, the file remains staged on JarvisSecure
    and the returned error lets callers fail closed. Never raises; failures
    return ``{"error": ...}``.
    """
    try:
        _os.makedirs(INBOX_PATH, exist_ok=True)

        sha256 = sha256_file(local_path)
        archive_name = _archive_name(doc_id, filename)
        inbox_file = str(Path(INBOX_PATH) / archive_name)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _move_sync, local_path, inbox_file)

        unraid_folder = TIER_TO_UNRAID.get(classification)
        if unraid_folder is not None:
            try:
                mirror_result = await loop.run_in_executor(
                    None,
                    lambda: mirror_file_to_unraid_ssh(
                        src_path=inbox_file,
                        folder=unraid_folder,
                        archive_name=archive_name,
                        sha256=sha256,
                    ),
                )
            except Exception as e:
                logger.exception(
                    "Unraid SSH mirror failed; file kept on JarvisSecure: %s", e
                )
                return {
                    "doc_id": doc_id,
                    "sha256": sha256,
                    "archive_path": inbox_file,
                    "tier": "nvme_only",
                    "classification": classification,
                    "unraid_folder": unraid_folder,
                    "archived_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(e),
                }
            archive_path = mirror_result["archive_path"]
            tier = "unraid"
        else:
            mirror_result = {}
            archive_path = inbox_file
            tier = "nvme_only"

        return {
            "doc_id": doc_id,
            "sha256": sha256,
            "archive_path": archive_path,
            "tier": tier,
            "classification": classification,
            "unraid_folder": unraid_folder,
            "unraid_remote_path": mirror_result.get("remote_path"),
            "archive_transport": mirror_result.get("transport"),
            "archived_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.exception("archive_document failed: %s", e)
        return {"error": str(e)}
