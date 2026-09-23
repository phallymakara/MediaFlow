"""License key verification, Ed25519 cryptography, and countdown management service."""

import base64
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
import hashlib
import logging
from pathlib import Path
import re
from typing import Optional, Union

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.config import DEFAULT_DEV_PRIVATE_KEY, DEFAULT_DEV_PUBLIC_KEY, get_config
from app.database.repository import SettingsRepository
from app.services.hardware import get_machine_id, verify_machine_id

logger = logging.getLogger(__name__)


class LicenseStatus(str, Enum):
    """Enumeration of possible license states."""

    ACTIVE = "active"
    EXPIRED = "expired"
    UNACTIVATED = "unactivated"
    TAMPERED = "tampered"
    INVALID = "invalid"


@dataclass
class LicenseInfo:
    """Represents the parsed license details and countdown status."""

    status: LicenseStatus
    is_valid: bool
    expires_at: Optional[str] = None
    days_remaining: int = 0
    hours_remaining: int = 0
    is_lifetime: bool = False
    tier: str = "standard"
    hwid: Optional[str] = None
    license_key: Optional[str] = None
    message: str = ""


def _load_public_key(key_input: Union[str, bytes, ed25519.Ed25519PublicKey]) -> ed25519.Ed25519PublicKey:
    """Load an Ed25519 public key from Base64, PEM, raw bytes, seed, or an instance."""
    if isinstance(key_input, ed25519.Ed25519PublicKey):
        return key_input

    if isinstance(key_input, str):
        key_str = key_input.strip()
        if Path(key_str).is_file():
            key_bytes = Path(key_str).read_bytes()
        elif "BEGIN PUBLIC KEY" in key_str:
            return serialization.load_pem_public_key(key_str.encode("utf-8"))  # type: ignore[return-value]
        else:
            try:
                decoded = base64.b64decode(key_str)
                if len(decoded) == 32:
                    key_bytes = decoded
                else:
                    seed = hashlib.sha256(key_str.encode("utf-8")).digest()
                    return ed25519.Ed25519PrivateKey.from_private_bytes(seed).public_key()
            except Exception:
                seed = hashlib.sha256(key_str.encode("utf-8")).digest()
                return ed25519.Ed25519PrivateKey.from_private_bytes(seed).public_key()
    elif isinstance(key_input, bytes):
        if len(key_input) == 32:
            key_bytes = key_input
        else:
            seed = hashlib.sha256(key_input).digest()
            return ed25519.Ed25519PrivateKey.from_private_bytes(seed).public_key()
    else:
        raise ValueError("Invalid public key type provided.")

    if len(key_bytes) == 32:
        return ed25519.Ed25519PublicKey.from_public_bytes(key_bytes)

    return serialization.load_pem_public_key(key_bytes)  # type: ignore[return-value]


def _load_private_key(key_input: Union[str, bytes, ed25519.Ed25519PrivateKey]) -> ed25519.Ed25519PrivateKey:
    """Load an Ed25519 private key from Base64, PEM, raw bytes, seed, or an instance."""
    if isinstance(key_input, ed25519.Ed25519PrivateKey):
        return key_input

    if isinstance(key_input, str):
        key_str = key_input.strip()
        if Path(key_str).is_file():
            key_bytes = Path(key_str).read_bytes()
        elif "BEGIN PRIVATE KEY" in key_str:
            return serialization.load_pem_private_key(key_str.encode("utf-8"), password=None)  # type: ignore[return-value]
        else:
            try:
                decoded = base64.b64decode(key_str)
                if len(decoded) == 32:
                    key_bytes = decoded
                else:
                    key_bytes = hashlib.sha256(key_str.encode("utf-8")).digest()
            except Exception:
                key_bytes = hashlib.sha256(key_str.encode("utf-8")).digest()
    elif isinstance(key_input, bytes):
        if len(key_input) == 32:
            key_bytes = key_input
        else:
            key_bytes = hashlib.sha256(key_input).digest()
    else:
        raise ValueError("Invalid private key type provided.")

    if len(key_bytes) == 32:
        return ed25519.Ed25519PrivateKey.from_private_bytes(key_bytes)

    return serialization.load_pem_private_key(key_bytes, password=None)  # type: ignore[return-value]



class LicenseService:
    """Cryptographic license verification and lifecycle management service."""

    PREFIX = "MDFL"
    LIFETIME_EXPIRY = "99991231"
    SETTING_KEY_LICENSE = "license:key"
    SETTING_KEY_LAST_CHECK = "license:last_check"

    def __init__(
        self,
        settings_repo: Optional[SettingsRepository] = None,
        public_key: Optional[Union[str, bytes, ed25519.Ed25519PublicKey]] = None,
        secret_key: Optional[str] = None,
        current_hwid: Optional[str] = None,
    ) -> None:
        """Initialize LicenseService with repository and verification public key.

        Args:
            settings_repo: Repository for persisting license and check timestamps.
            public_key: Ed25519 public key (Base64, PEM, or raw bytes).
            secret_key: Legacy parameter alias for backwards compatibility.
            current_hwid: Optional HWID override for testing.
        """
        self._repo = settings_repo
        self._current_hwid = current_hwid

        if secret_key is not None:
            if len(secret_key) < 16:
                raise ValueError("License secret key must be at least 16 characters long.")
            self._secret = secret_key.encode("utf-8")
        else:
            self._secret = b""

        config = get_config()
        raw_key = public_key or secret_key or config.license_public_key or DEFAULT_DEV_PUBLIC_KEY
        try:
            self._public_key = _load_public_key(raw_key)
        except Exception as exc:
            logger.warning("Failed to load configured public key (%s), falling back to default.", exc)
            self._public_key = _load_public_key(DEFAULT_DEV_PUBLIC_KEY)

    @classmethod
    def generate_key(
        cls,
        expires_at: Optional[date] = None,
        tier: str = "standard",
        hwid: str = "ANY",
        uid: str = "",
        private_key: Optional[Union[str, bytes, ed25519.Ed25519PrivateKey]] = None,
        secret_key: Optional[str] = None,
    ) -> str:
        """Generate a cryptographically signed license product key using Ed25519.

        Args:
            expires_at: Expiration date, or None for a Lifetime license.
            tier: License tier string (e.g. standard, pro).
            hwid: Machine ID to bind license to, or 'ANY' for portable license.
            uid: Optional customer identifier or salt.
            private_key: Vendor Ed25519 signing private key.
            secret_key: Legacy alias for private_key parameter.

        Returns:
            Formatted license key (e.g. MDFL-XXXXX-XXXXX-XXXXX-...).
        """
        exp_str = expires_at.strftime("%Y%m%d") if expires_at else cls.LIFETIME_EXPIRY
        clean_tier = re.sub(r"[^a-zA-Z0-9]", "", tier).lower()[:4] or "std"
        clean_hwid = re.sub(r"[^a-zA-Z0-9\-\*]", "", hwid).upper() or "ANY"
        clean_uid = re.sub(r"[^a-zA-Z0-9]", "", uid).upper()[:12] or "USER"

        payload = f"{exp_str}:{clean_tier}:{clean_hwid}:{clean_uid}"
        payload_bytes = payload.encode("utf-8")

        config = get_config()
        raw_priv = private_key or secret_key or config.license_private_key or DEFAULT_DEV_PRIVATE_KEY
        priv = _load_private_key(raw_priv)

        signature = priv.sign(payload_bytes)

        # Binary packet: 1 byte payload length + payload + 64 bytes signature
        packet = bytes([len(payload_bytes)]) + payload_bytes + signature
        encoded = base64.b32encode(packet).decode("utf-8").rstrip("=")

        chunks = [encoded[i : i + 5] for i in range(0, len(encoded), 5)]
        return f"{cls.PREFIX}-" + "-".join(chunks)

    def verify_key(self, key: str) -> LicenseInfo:
        """Verify the cryptographic signature, format, HWID, and expiration of a license key.

        Args:
            key: License key string to verify.

        Returns:
            LicenseInfo object describing validation result and remaining countdown.
        """
        if not key or not isinstance(key, str):
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                is_valid=False,
                message="License key is empty or invalid.",
            )

        clean_key = key.strip().upper()
        if not clean_key.startswith(f"{self.PREFIX}-"):
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                is_valid=False,
                message="Invalid license key format.",
            )

        body = clean_key[len(self.PREFIX) + 1 :].replace("-", "")
        padding = (8 - (len(body) % 8)) % 8
        padded_b32 = body + ("=" * padding)

        try:
            packet = base64.b32decode(padded_b32.encode("utf-8"))
        except Exception as exc:
            logger.debug("Base32 decoding failed for license key: %s", exc)
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                is_valid=False,
                message="Failed to decode license key.",
            )

        if len(packet) < 66:  # 1 byte len + at least 1 byte payload + 64 bytes sig
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                is_valid=False,
                message="Corrupted license key structure.",
            )

        p_len = packet[0]
        if len(packet) < 1 + p_len + 64:
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                is_valid=False,
                message="Corrupted license key structure.",
            )

        payload_bytes = packet[1 : 1 + p_len]
        signature_bytes = packet[1 + p_len : 1 + p_len + 64]

        # Verify Ed25519 signature
        try:
            self._public_key.verify(signature_bytes, payload_bytes)
        except InvalidSignature:
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                is_valid=False,
                message="License signature verification failed.",
            )
        except Exception as exc:
            logger.debug("Signature verification error: %s", exc)
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                is_valid=False,
                message="License verification failed.",
            )

        # Parse verified payload
        try:
            payload_str = payload_bytes.decode("utf-8")
            parts = payload_str.split(":")
            if len(parts) != 4:
                return LicenseInfo(
                    status=LicenseStatus.INVALID,
                    is_valid=False,
                    message="Invalid payload structure in license.",
                )
            exp_str, tier, hwid, uid = parts
        except Exception:
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                is_valid=False,
                message="Corrupted payload in license key.",
            )

        # Verify Machine ID (HWID) binding
        if not verify_machine_id(hwid, current_id=self._current_hwid):
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                is_valid=False,
                tier=tier,
                hwid=hwid,
                license_key=clean_key,
                message=f"License is registered to a different device ({hwid}).",
            )

        # Parse lifetime status
        if exp_str == self.LIFETIME_EXPIRY:
            return LicenseInfo(
                status=LicenseStatus.ACTIVE,
                is_valid=True,
                is_lifetime=True,
                days_remaining=99999,
                hours_remaining=999999,
                tier=tier,
                hwid=hwid,
                license_key=clean_key,
                message="Lifetime license active.",
            )

        # Parse expiration date
        try:
            exp_date = datetime.strptime(exp_str, "%Y%m%d").replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc
            )
        except ValueError:
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                is_valid=False,
                message="Invalid expiration date encoded in license.",
            )

        now_utc = datetime.now(timezone.utc)
        time_diff = exp_date - now_utc

        if time_diff.total_seconds() <= 0:
            return LicenseInfo(
                status=LicenseStatus.EXPIRED,
                is_valid=False,
                expires_at=exp_date.strftime("%Y-%m-%d"),
                days_remaining=0,
                hours_remaining=0,
                tier=tier,
                hwid=hwid,
                license_key=clean_key,
                message=f"License expired on {exp_date.strftime('%Y-%m-%d')}.",
            )

        days_remaining = int(time_diff.total_seconds() // 86400)
        hours_remaining = int((time_diff.total_seconds() % 86400) // 3600)

        return LicenseInfo(
            status=LicenseStatus.ACTIVE,
            is_valid=True,
            expires_at=exp_date.strftime("%Y-%m-%d"),
            days_remaining=days_remaining,
            hours_remaining=hours_remaining,
            tier=tier,
            hwid=hwid,
            license_key=clean_key,
            message=f"License active: {days_remaining} days remaining.",
        )

    def activate(self, key: str) -> LicenseInfo:
        """Validate and persist an active license key into the database.

        Args:
            key: License key string to activate.

        Returns:
            LicenseInfo object with activation status.
        """
        info = self.verify_key(key)
        if not info.is_valid:
            logger.warning("License activation rejected: %s", info.message)
            return info

        if self._repo:
            now_iso = datetime.now(timezone.utc).isoformat()
            self._repo.set(self.SETTING_KEY_LICENSE, key.strip().upper())
            self._repo.set(self.SETTING_KEY_LAST_CHECK, now_iso)
            logger.info("License key activated successfully (tier: %s, days: %d).", info.tier, info.days_remaining)

        return info

    def deactivate(self) -> bool:
        """Clear currently stored license key from database.

        Returns:
            True if key was cleared.
        """
        if self._repo:
            self._repo.set(self.SETTING_KEY_LICENSE, "")
            logger.info("License deactivated.")
            return True
        return False

    def get_current_license(self) -> LicenseInfo:
        """Verify the currently stored license key against expiration and clock rollback tampering.

        Returns:
            LicenseInfo object for current stored key or UNACTIVATED if no key stored.
        """
        if not self._repo:
            return LicenseInfo(
                status=LicenseStatus.UNACTIVATED,
                is_valid=False,
                message="No repository available.",
            )

        stored_key = self._repo.get(self.SETTING_KEY_LICENSE)
        if not stored_key or not stored_key.strip():
            return LicenseInfo(
                status=LicenseStatus.UNACTIVATED,
                is_valid=False,
                message="Application is not activated.",
            )

        # Detect potential clock tampering against last recorded check timestamp
        last_check_str = self._repo.get(self.SETTING_KEY_LAST_CHECK)
        if last_check_str:
            try:
                last_check = datetime.fromisoformat(last_check_str)
                now_utc = datetime.now(timezone.utc)
                if now_utc < (last_check.replace(tzinfo=timezone.utc) if last_check.tzinfo is None else last_check):
                    logger.warning("System clock rollback detected: current=%s, last_check=%s", now_utc, last_check)
                    return LicenseInfo(
                        status=LicenseStatus.TAMPERED,
                        is_valid=False,
                        license_key=stored_key,
                        message="System clock rollback detected. Verification suspended.",
                    )
            except Exception as exc:
                logger.debug("Failed parsing last check timestamp: %s", exc)

        info = self.verify_key(stored_key)

        if info.is_valid:
            now_iso = datetime.now(timezone.utc).isoformat()
            self._repo.set(self.SETTING_KEY_LAST_CHECK, now_iso)

        return info

    def is_download_allowed(self) -> bool:
        """Check if media downloads are permitted under current license status.

        Returns:
            True if license is active and valid, False otherwise.
        """
        info = self.get_current_license()
        return info.is_valid and info.status == LicenseStatus.ACTIVE

    verify_active_license = get_current_license

