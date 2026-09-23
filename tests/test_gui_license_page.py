"""Unit tests for LicensePage helper logic, masking, badge derivation, and activation."""

from datetime import date, timedelta
from pathlib import Path
import pytest

from app.database.database import DatabaseManager
from app.database.repository import SettingsRepository
from app.gui.license_page import (
    clean_product_key_input,
    get_license_badge_properties,
    mask_license_key,
)
from app.services.license import LicenseInfo, LicenseService, LicenseStatus


def test_clean_product_key_input() -> None:
    """Verify license key input sanitization and uppercase conversion."""
    assert clean_product_key_input("  mdfl-1234-abcd  ") == "MDFL-1234-ABCD"
    assert clean_product_key_input("") == ""
    assert clean_product_key_input(None) == ""


def test_mask_license_key_standard() -> None:
    """Verify inner segments of standard product keys are masked."""
    raw_key = "MDFL-AAAA-BBBB-CCCC-DDDD"
    masked = mask_license_key(raw_key)
    assert masked == "MDFL-AAAA-****-****-DDDD"


def test_mask_license_key_edge_cases() -> None:
    """Verify masking edge cases for None, empty, or short strings."""
    assert mask_license_key(None) == "None"
    assert mask_license_key("") == "None"
    assert mask_license_key("MDFL-SHORT") == "MDFL-SHORT"


def test_get_license_badge_properties_active_lifetime() -> None:
    """Verify badge properties for active lifetime license."""
    info = LicenseInfo(
        status=LicenseStatus.ACTIVE,
        is_valid=True,
        is_lifetime=True,
        days_remaining=99999,
        tier="pro",
    )
    text, bg, color = get_license_badge_properties(info)
    assert "Lifetime" in text
    assert bg != ""
    assert color != ""


def test_get_license_badge_properties_active_expiring() -> None:
    """Verify badge properties for active time-limited license."""
    info = LicenseInfo(
        status=LicenseStatus.ACTIVE,
        is_valid=True,
        is_lifetime=False,
        days_remaining=45,
        tier="pro",
    )
    text, bg, color = get_license_badge_properties(info)
    assert "45d remaining" in text


def test_get_license_badge_properties_tampered() -> None:
    """Verify badge properties when system clock rollback is detected."""
    info = LicenseInfo(
        status=LicenseStatus.TAMPERED,
        is_valid=False,
    )
    text, bg, color = get_license_badge_properties(info)
    assert "Clock Error" in text


def test_get_license_badge_properties_expired() -> None:
    """Verify badge properties for expired license."""
    info = LicenseInfo(
        status=LicenseStatus.EXPIRED,
        is_valid=False,
    )
    text, bg, color = get_license_badge_properties(info)
    assert "Expired" in text


def test_get_license_badge_properties_unactivated() -> None:
    """Verify badge properties for unactivated license."""
    info = LicenseInfo(
        status=LicenseStatus.UNACTIVATED,
        is_valid=False,
    )
    text, bg, color = get_license_badge_properties(info)
    assert "Unactivated" in text


def test_license_service_roundtrip(tmp_path: Path) -> None:
    """Verify full activation and deactivation lifecycle using SQLite repository."""
    db_file = tmp_path / "test_license.db"
    db_manager = DatabaseManager(db_path=db_file)
    repo = SettingsRepository(db_manager=db_manager)
    service = LicenseService(settings_repo=repo)

    # Initial state: unactivated
    initial = service.get_current_license()
    assert initial.status == LicenseStatus.UNACTIVATED
    assert not initial.is_valid

    # Generate a valid key
    future_date = date.today() + timedelta(days=90)
    key = LicenseService.generate_key(expires_at=future_date, tier="pro", uid="TEST")

    # Activate
    activated = service.activate(key)
    assert activated.is_valid
    assert activated.status == LicenseStatus.ACTIVE
    assert activated.tier == "pro"
    assert activated.days_remaining >= 89

    # Verify retrieval
    current = service.get_current_license()
    assert current.is_valid
    assert current.status == LicenseStatus.ACTIVE

    # Deactivate
    deactivated = service.deactivate()
    assert deactivated
    after_deactivation = service.get_current_license()
    assert after_deactivation.status == LicenseStatus.UNACTIVATED
    assert not after_deactivation.is_valid
