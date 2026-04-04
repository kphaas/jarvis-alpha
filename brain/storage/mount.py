import asyncio
import os
import subprocess
from datetime import datetime, timezone

from jarvis_common.logging_config import get_logger
from brain.core.secrets import get_secret

MOUNT_PATH = "/Volumes/Documents"
NAS_HOST = "192.168.30.10"
NAS_SHARE = "Documents"
HEALTH_PROBE = ".jarvis_alpha_health"

logger = get_logger("alpha_brain")


def is_mounted() -> bool:
    return os.path.exists(MOUNT_PATH) and os.path.ismount(MOUNT_PATH)


def is_writable() -> bool:
    probe = os.path.join(MOUNT_PATH, HEALTH_PROBE)
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def mount_health() -> dict:
    return {
        "mounted": is_mounted(),
        "writable": is_writable() if is_mounted() else False,
        "path": MOUNT_PATH,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _remount_sync(user: str, password: str) -> None:
    subprocess.run(
        ["umount", "-f", MOUNT_PATH],
        capture_output=True,
        check=False,
    )
    subprocess.run(
        [
            "mount_smbfs",
            f"smb://{user}:{password}@{NAS_HOST}/{NAS_SHARE}",
            MOUNT_PATH,
        ],
        capture_output=True,
        check=False,
    )


async def ensure_mounted() -> dict:
    try:
        health = mount_health()
        if health["mounted"] and health["writable"]:
            return {**health, "action": "none"}

        try:
            user = get_secret("UNRAID_SMB_USER")
            password = get_secret("UNRAID_SMB_PASS")
        except Exception as e:
            logger.warning("Missing SMB credentials: %s", e)
            health = mount_health()
            return {**health, "action": "failed", "error": str(e)}

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _remount_sync, user, password)

        health = mount_health()
        if health["mounted"] and health["writable"]:
            return {**health, "action": "remounted"}
        return {**health, "action": "failed"}
    except Exception as e:
        logger.exception("ensure_mounted failed: %s", e)
        try:
            health = mount_health()
        except Exception:
            health = {
                "mounted": False,
                "writable": False,
                "path": MOUNT_PATH,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        return {**health, "action": "failed", "error": str(e)}
