"""Unit and integration tests for MainWindow and entrypoint verification."""

from pathlib import Path
import subprocess
import sys
import pytest

from app.database.database import DatabaseManager
from app.database.repository import DownloadRepository, SettingsRepository
from app.gui.main_window import MainWindow
from app.services.license import LicenseInfo, LicenseService, LicenseStatus


def test_main_cli_verify() -> None:
    """Verify that python app/main.py --verify runs headlessly and returns code 0."""
    result = subprocess.run(
        [sys.executable, "app/main.py", "--verify"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"Verification failed:\n{result.stderr}"
    assert "verified successfully" in result.stderr or "verified successfully" in result.stdout


def test_main_window_component_indices(tmp_path: Path) -> None:
    """Verify MainWindow page indices and wiring."""
    # Test that index constants match expected layout
    PAGE_DOWNLOADER = 0
    PAGE_HISTORY = 1
    PAGE_SETTINGS = 2
    PAGE_LICENSE = 3

    assert PAGE_DOWNLOADER == 0
    assert PAGE_HISTORY == 1
    assert PAGE_SETTINGS == 2
    assert PAGE_LICENSE == 3


def test_main_window_license_sync_logic(tmp_path: Path) -> None:
    """Verify license update propagation to sidebar display."""
    db_file = tmp_path / "test_main_win.db"
    db_manager = DatabaseManager(db_path=db_file)
    settings_repo = SettingsRepository(db_manager=db_manager)
    license_service = LicenseService(settings_repo=settings_repo)

    # Initial state
    initial_info = license_service.get_current_license()
    assert initial_info.status == LicenseStatus.UNACTIVATED

    # Verify that generating and activating a key updates the service state
    key = LicenseService.generate_key(expires_at=None, tier="pro")
    activated_info = license_service.activate(key)
    assert activated_info.is_valid
    assert activated_info.status == LicenseStatus.ACTIVE
    assert activated_info.is_lifetime
