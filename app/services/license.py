"""License key verification and countdown management service."""

import base64
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
import hashlib
import hmac
import logging
import re
from typing import Optional

from app.config import get_config
from app.database.repository import SettingsRepository

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
    license_key: Optional[str] = None
    message: str = ""


class LicenseService:
    """Cryptographic license verification and lifecycle management service."""

    PREFIX = "MDFL"
    LIFETIME_EXPIRY = "99991231"
    SETTING_KEY_LICENSE = "license:key"
    SETTING_KEY_LAST_CHECK = "license:last_check"

    def __init__(
        self,
        settings_repo: Optional[SettingsRepository] = None,
        secret_key: Optional[str] = None,
    ) -> None:
        """Initialize LicenseService with optional settings repository and secret key.

        Args:
            settings_repo: Repository for persisting license and check timestamps.
            secret_key: Secret HMAC key used for signing and verification.
        """
        self._repo = settings_repo
        config = get_config()
        self._secret = (secret_key or config.license_secret).encode("utf-8")

    @classmethod
    def generate_key(
        cls,
        expires_at: Optional[date] = None,
        tier: str = "standard",
        uid: str = "",
        secret_key: Optional[str] = None,
    ) -> str:
        """Generate a cryptographically signed license product key.

        Args:
            expires_at: Expiration date, or None for a Lifetime license.
            tier: License tier string (e.g. standard, pro).
            uid: Optional customer identifier or salt.
            secret_key: Optional signing key override.

        Returns:
            Formatted license key (e.g. MDFL-XXXX-XXXX-XXXX-XXXX).
        """
        exp_str = expires_at.strftime("%Y%m%d") if expires_at else cls.LIFETIME_EXPIRY
        clean_tier = re.sub(r"[^a-zA-Z0-9]", "", tier).lower()[:4] or "std"
        clean_uid = re.sub(r"[^a-zA-Z0-9]", "", uid).upper()[:6] or "USER"

        payload = f"{exp_str}:{clean_tier}:{clean_uid}"

        config_secret = secret_key or get_config().license_secret
        sig = hmac.new(config_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:8]

        combined = f"{payload}:{sig}"
        encoded = base64.b32encode(combined.encode("utf-8")).decode("utf-8").rstrip("=")

        # Format into clean 4-character blocks
        chunks = [encoded[i : i + 4] for i in range(0, len(encoded), 4)]
        return f"{cls.PREFIX}-" + "-".join(chunks)

    def verify_key(self, key: str) -> LicenseInfo:
        """Verify the cryptographic signature, format, and expiration of a license key.

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
        # Restore Base32 padding
        padding = (8 - (len(body) % 8)) % 8
        padded_b32 = body + ("=" * padding)

        try:
            decoded = base64.b32decode(padded_b32.encode("utf-8")).decode("utf-8")
            parts = decoded.split(":")
            if len(parts) != 4:
                return LicenseInfo(
                    status=LicenseStatus.INVALID,
                    is_valid=False,
                    message="Corrupted license key structure.",
                )
            exp_str, tier, uid, sig = parts
        except Exception as exc:
            logger.debug("Base32 decoding failed for license key: %s", exc)
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                is_valid=False,
                message="Failed to decode license key.",
            )

        # Verify cryptographic HMAC signature
        payload = f"{exp_str}:{tier}:{uid}"
        expected_sig = hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:8]

        if not hmac.compare_digest(sig.lower(), expected_sig.lower()):
            return LicenseInfo(
                status=LicenseStatus.INVALID,
                is_valid=False,
                message="License signature verification failed.",
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
        """Retrieve stored license, verify its validity, and check for clock tampering.

        Returns:
            LicenseInfo reflecting current runtime status.
        """
        if not self._repo:
            return LicenseInfo(
                status=LicenseStatus.UNACTIVATED,
                is_valid=False,
                message="No license repository configured.",
            )

        stored_key = self._repo.get(self.SETTING_KEY_LICENSE, "")
        if not stored_key or not stored_key.strip():
            return LicenseInfo(
                status=LicenseStatus.UNACTIVATED,
                is_valid=False,
                message="MediaFlow is not activated. Please enter a license key.",
            )

        # Clock-tampering verification
        now_utc = datetime.now(timezone.utc)
        last_check_iso = self._repo.get(self.SETTING_KEY_LAST_CHECK)

        if last_check_iso:
            try:
                last_check = datetime.fromisoformat(last_check_iso)
                # If current time is more than 5 minutes before last recorded check
                if (last_check - now_utc).total_seconds() > 300:
                    logger.warning(
                        "System clock rollback detected. Current: %s, Last check: %s",
                        now_utc.isoformat(),
                        last_check_iso,
                    )
                    return LicenseInfo(
                        status=LicenseStatus.TAMPERED,
                        is_valid=False,
                        license_key=stored_key,
                        message="System clock rollback detected. Please restore correct date and time.",
                    )
            except Exception as exc:
                logger.debug("Failed parsing last check timestamp: %s", exc)

        info = self.verify_key(stored_key)

        # Update last check timestamp if license is active
        if info.is_valid:
            self._repo.set(self.SETTING_KEY_LAST_CHECK, now_utc.isoformat())

        return info

    def is_download_allowed(self) -> bool:
        """Check if media downloads are permitted under current license status.

        Returns:
            True if license is active and valid, False otherwise.
        """
        info = self.get_current_license()
        return info.is_valid and info.status == LicenseStatus.ACTIVE
