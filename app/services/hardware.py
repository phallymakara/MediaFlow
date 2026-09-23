"""Cross-platform hardware identification and fingerprinting service."""

import hashlib
import logging
import os
import platform
import re
import subprocess
import sys
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

HARDWARE_SALT = "mediaflow_hwid_salt_v1_secure"


def _get_macos_uuid() -> Optional[str]:
    """Retrieve macOS hardware IOPlatformUUID via ioreg command."""
    try:
        output = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            text=True,
            timeout=2,
            stderr=subprocess.DEVNULL,
        )
        match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', output)
        if match:
            return match.group(1).strip()
    except Exception as exc:
        logger.debug("Failed to read macOS IOPlatformUUID: %s", exc)
    return None


def _get_windows_uuid() -> Optional[str]:
    """Retrieve Windows MachineGuid from Windows Registry or wmic."""
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            val, _ = winreg.QueryValueEx(key, "MachineGuid")
            if val:
                return str(val).strip()
    except Exception as exc:
        logger.debug("winreg MachineGuid query failed: %s", exc)

    try:
        output = subprocess.check_output(
            ["wmic", "csproduct", "get", "uuid"],
            text=True,
            timeout=2,
            stderr=subprocess.DEVNULL,
        )
        lines = [line.strip() for line in output.splitlines() if line.strip() and "UUID" not in line]
        if lines:
            return lines[0]
    except Exception as exc:
        logger.debug("wmic query failed: %s", exc)

    return None


def _get_linux_uuid() -> Optional[str]:
    """Retrieve Linux machine-id from /etc/machine-id or dbus."""
    for path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        return content
        except Exception as exc:
            logger.debug("Failed reading Linux machine-id from %s: %s", path, exc)
    return None


def get_raw_machine_uuid() -> str:
    """Detect platform and retrieve the raw underlying hardware UUID.

    Returns:
        String representing raw hardware identifier, or stable fallback.
    """
    system = platform.system().lower()
    raw: Optional[str] = None

    if system == "darwin":
        raw = _get_macos_uuid()
    elif system == "windows":
        raw = _get_windows_uuid()
    elif system == "linux":
        raw = _get_linux_uuid()

    if not raw:
        # Fallback to stable MAC address node if platform query fails
        mac_node = uuid.getnode()
        raw = f"fallback-{platform.node()}-{mac_node}"

    return raw


def get_machine_id(salt: str = HARDWARE_SALT) -> str:
    """Generate a clean, standardized, salted hardware identifier.

    Format: MDFL-HWID-XXXX-XXXX (e.g. MDFL-HWID-60A4-0FE6)

    Args:
        salt: Salt string to prevent cross-application fingerprint tracking.

    Returns:
        Formatted Machine ID string.
    """
    raw_uuid = get_raw_machine_uuid()
    salted = f"{salt}:{raw_uuid}".encode("utf-8")
    digest = hashlib.sha256(salted).hexdigest().upper()
    part1 = digest[0:4]
    part2 = digest[4:8]
    return f"MDFL-HWID-{part1}-{part2}"


def verify_machine_id(candidate: Optional[str], current_id: Optional[str] = None) -> bool:
    """Check whether a candidate HWID matches the current machine or wildcard.

    Args:
        candidate: Candidate HWID string from license payload.
        current_id: Optional current machine ID override for testing.

    Returns:
        True if candidate matches or is a wildcard ('ANY'), False otherwise.
    """
    if not candidate:
        return False

    clean_candidate = candidate.strip().upper()
    if clean_candidate in ("ANY", "ALL", "*"):
        return True

    active_id = (current_id or get_machine_id()).strip().upper()
    # Support comparing either full MDFL-HWID-XXXX-XXXX or just XXXX-XXXX
    if clean_candidate == active_id:
        return True

    candidate_short = clean_candidate.replace("MDFL-HWID-", "").replace("-", "")
    active_short = active_id.replace("MDFL-HWID-", "").replace("-", "")
    return candidate_short == active_short
