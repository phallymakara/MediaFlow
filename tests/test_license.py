"""Tests for offline license verification, countdown calculations, and activation."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pytest

from app.database.database import DatabaseManager
from app.database.repository import SettingsRepository
from app.services.license import LicenseInfo, LicenseService, LicenseStatus


@pytest.fixture
def temp_settings_repo() -> SettingsRepository:
    """Fixture providing a clean SQLite settings repository."""
    db_manager = DatabaseManager(db_path=":memory:")
    return SettingsRepository(db_manager=db_manager)


def test_license_key_generation_and_verification() -> None:
    """Verify that generated 30-day key decodes correctly and calculates countdown."""
    service = LicenseService(secret_key="test_secret_key_12345")
    exp_date = (datetime.now(timezone.utc) + timedelta(days=30)).date()

    key = LicenseService.generate_key(
        expires_at=exp_date,
        tier="pro",
        uid="CLIENT1",
        secret_key="test_secret_key_12345",
    )

    assert key.startswith("MDFL-")
    info = service.verify_key(key)

    assert info.is_valid is True
    assert info.status == LicenseStatus.ACTIVE
    assert info.tier == "pro"
    assert info.is_lifetime is False
    assert info.days_remaining in (29, 30)
    assert info.expires_at == exp_date.strftime("%Y-%m-%d")


def test_lifetime_license_key() -> None:
    """Verify that lifetime key is active and marked as permanent."""
    service = LicenseService(secret_key="test_secret_key_12345")

    key = LicenseService.generate_key(
        expires_at=None,
        tier="lifetime",
        uid="ADMIN",
        secret_key="test_secret_key_12345",
    )

    info = service.verify_key(key)
    assert info.is_valid is True
    assert info.status == LicenseStatus.ACTIVE
    assert info.is_lifetime is True
    assert info.days_remaining > 10000


def test_expired_license_key() -> None:
    """Verify that a key with past expiration date returns EXPIRED status."""
    service = LicenseService(secret_key="test_secret_key_12345")
    past_date = (datetime.now(timezone.utc) - timedelta(days=5)).date()

    key = LicenseService.generate_key(
        expires_at=past_date,
        tier="standard",
        uid="EXPIRED_USER",
        secret_key="test_secret_key_12345",
    )

    info = service.verify_key(key)
    assert info.is_valid is False
    assert info.status == LicenseStatus.EXPIRED
    assert info.days_remaining == 0
    assert "expired" in info.message.lower()


def test_forged_or_tampered_license_key() -> None:
    """Verify that a modified key fails HMAC cryptographic verification."""
    service = LicenseService(secret_key="test_secret_key_12345")
    exp_date = (datetime.now(timezone.utc) + timedelta(days=30)).date()

    valid_key = LicenseService.generate_key(
        expires_at=exp_date,
        tier="standard",
        secret_key="test_secret_key_12345",
    )

    # Tamper with the key body
    tampered_key = valid_key[:-2] + ("A" if valid_key[-2] != "A" else "B") + valid_key[-1]
    info = service.verify_key(tampered_key)

    assert info.is_valid is False
    assert info.status == LicenseStatus.INVALID


def test_invalid_key_formats() -> None:
    """Verify rejection of empty, malformed, or wrong prefix keys."""
    service = LicenseService(secret_key="test_secret_key_12345")

    assert service.verify_key("").is_valid is False
    assert service.verify_key("INVALID-PREFIX-1234").is_valid is False
    assert service.verify_key("MDFL-SHORT").is_valid is False


def test_license_activation_and_persistence(temp_settings_repo: SettingsRepository) -> None:
    """Verify full activation lifecycle in SQLite database."""
    service = LicenseService(settings_repo=temp_settings_repo, secret_key="test_secret_key_12345")

    # Initial state: unactivated
    initial_info = service.get_current_license()
    assert initial_info.status == LicenseStatus.UNACTIVATED
    assert service.is_download_allowed() is False

    # Generate valid key
    exp_date = (datetime.now(timezone.utc) + timedelta(days=14)).date()
    key = LicenseService.generate_key(
        expires_at=exp_date,
        tier="standard",
        uid="BUYER",
        secret_key="test_secret_key_12345",
    )

    # Activate
    activation_info = service.activate(key)
    assert activation_info.is_valid is True
    assert activation_info.status == LicenseStatus.ACTIVE

    # Verify retrieved current state
    current_info = service.get_current_license()
    assert current_info.is_valid is True
    assert current_info.status == LicenseStatus.ACTIVE
    assert current_info.days_remaining in (13, 14)
    assert service.is_download_allowed() is True


def test_deactivation(temp_settings_repo: SettingsRepository) -> None:
    """Verify license deactivation clears database setting."""
    service = LicenseService(settings_repo=temp_settings_repo, secret_key="test_secret_key_12345")
    key = LicenseService.generate_key(
        expires_at=(datetime.now(timezone.utc) + timedelta(days=10)).date(),
        secret_key="test_secret_key_12345",
    )

    service.activate(key)
    assert service.is_download_allowed() is True

    service.deactivate()
    assert service.get_current_license().status == LicenseStatus.UNACTIVATED
    assert service.is_download_allowed() is False


def test_anti_clock_tamper_detection(temp_settings_repo: SettingsRepository) -> None:
    """Verify that moving system clock backward triggers TAMPERED status."""
    service = LicenseService(settings_repo=temp_settings_repo, secret_key="test_secret_key_12345")
    key = LicenseService.generate_key(
        expires_at=(datetime.now(timezone.utc) + timedelta(days=30)).date(),
        secret_key="test_secret_key_12345",
    )

    service.activate(key)

    # Simulate clock tampering by setting last_check to 10 days in the future
    future_time = datetime.now(timezone.utc) + timedelta(days=10)
    temp_settings_repo.set(service.SETTING_KEY_LAST_CHECK, future_time.isoformat())

    info = service.get_current_license()
    assert info.status == LicenseStatus.TAMPERED
    assert info.is_valid is False
    assert service.is_download_allowed() is False
    assert "rollback" in info.message.lower()
