import asyncio
import hashlib
import os as _os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from brain.config.logging_config import get_logger
from brain.core.secrets import get_secret  # noqa: F401
from brain.storage.mount import ensure_mounted

JARVIS_SECURE = _os.environ.get("ALPHA_NVME_PATH", "/Volumes/JarvisSecure")
UNRAID_ROOT = _os.environ.get("ALPHA_UNRAID_PATH", "/Volumes/Documents")
INBOX_PATH = f"{JARVIS_SECURE}/03_staging/inbox"

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


def _atomic_copy2_sync(src: str, dst: str) -> None:
    dst_tmp = f"{dst}.tmp"
    shutil.copy2(src, dst_tmp)
    _os.replace(dst_tmp, dst)


async def archive_document(
    local_path: str,
    filename: str,
    classification: str,
    doc_id: str,
) -> dict:
    """
    Stage the file on JarvisSecure inbox, optionally mirror to Unraid by classification.

    Hashes before move, then moves into the inbox. For tiers mapped to Unraid,
    ensures the SMB share is mounted and copies atomically to the tier folder;
    otherwise the file remains on NVMe only. Never raises; failures return
    ``{"error": ...}``.
    """
    try:
        _os.makedirs(INBOX_PATH, exist_ok=True)

        sha256 = sha256_file(local_path)
        inbox_file = str(Path(INBOX_PATH) / filename)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _move_sync, local_path, inbox_file)

        unraid_folder = TIER_TO_UNRAID.get(classification)
        if unraid_folder is not None:
            mount_result = await ensure_mounted()
            if mount_result.get("mounted") and mount_result.get("writable"):
                dst_dir = f"{UNRAID_ROOT}/{unraid_folder}"
                dst = f"{dst_dir}/{filename}"
                _os.makedirs(dst_dir, exist_ok=True)
                await loop.run_in_executor(None, _atomic_copy2_sync, inbox_file, dst)
                archive_path = dst
                tier = "unraid"
            else:
                archive_path = inbox_file
                tier = "nvme_only"
                logger.warning(
                    "Unraid not mounted — file kept on JarvisSecure",
                )
        else:
            archive_path = inbox_file
            tier = "nvme_only"

        return {
            "doc_id": doc_id,
            "sha256": sha256,
            "archive_path": archive_path,
            "tier": tier,
            "classification": classification,
            "unraid_folder": unraid_folder,
            "archived_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.exception("archive_document failed: %s", e)
        return {"error": str(e)}
