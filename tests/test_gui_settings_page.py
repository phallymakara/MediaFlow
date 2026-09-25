"""Unit tests for SettingsPage helper logic, validation, and persistence."""

from pathlib import Path
import tempfile
import pytest

from app.database.database import DatabaseManager
from app.database.repository import SettingsRepository
from app.gui.settings_page import (
    KEY_COOKIES_BROWSER,
    KEY_COOKIES_FILE,
    KEY_DOWNLOAD_DIR,
    KEY_FFMPEG_PATH,
    KEY_MAX_CONCURRENT,
    clamp_concurrency,
    resolve_ffmpeg_status,
    validate_cookies_file,
    validate_download_directory,
)


def test_clamp_concurrency_boundaries() -> None:
    """Verify concurrency input is properly clamped between 1 and 20."""
    assert clamp_concurrency(0) == 1
    assert clamp_concurrency(-5) == 1
    assert clamp_concurrency(1) == 1
    assert clamp_concurrency(10) == 10
    assert clamp_concurrency(20) == 20
    assert clamp_concurrency(21) == 20
    assert clamp_concurrency(100) == 20
    assert clamp_concurrency("invalid") == 3
    assert clamp_concurrency(None) == 3


def test_validate_download_directory_empty() -> None:
    """Verify empty or whitespace directory paths are rejected."""
    is_valid, msg = validate_download_directory("")
    assert not is_valid
    assert "empty" in msg.lower()

    is_valid_none, _ = validate_download_directory(None)
    assert not is_valid_none


def test_validate_download_directory_valid(tmp_path: Path) -> None:
    """Verify existing writable directory passes validation."""
    target_dir = tmp_path / "valid_downloads"
    target_dir.mkdir()

    is_valid, resolved = validate_download_directory(str(target_dir))
    assert is_valid
    assert Path(resolved).resolve() == target_dir.resolve()


def test_validate_download_directory_creates_if_missing(tmp_path: Path) -> None:
    """Verify non-existent directory path within writable parent is created automatically."""
    target_dir = tmp_path / "new_nested" / "downloads"
    assert not target_dir.exists()

    is_valid, resolved = validate_download_directory(str(target_dir))
    assert is_valid
    assert target_dir.exists()
    assert Path(resolved).resolve() == target_dir.resolve()


def test_validate_download_directory_rejects_file(tmp_path: Path) -> None:
    """Verify that a path pointing to a regular file is rejected."""
    dummy_file = tmp_path / "dummy.txt"
    dummy_file.write_text("not a directory")

    is_valid, msg = validate_download_directory(str(dummy_file))
    assert not is_valid
    assert "not a directory" in msg.lower()


def test_resolve_ffmpeg_status_custom_file(tmp_path: Path) -> None:
    """Verify custom file resolution when executable exists."""
    custom_bin = tmp_path / "ffmpeg.exe"
    custom_bin.write_bytes(b"dummy binary content")

    is_avail, desc = resolve_ffmpeg_status(str(custom_bin))
    assert is_avail
    assert "Custom executable located" in desc


def test_resolve_ffmpeg_status_custom_missing(tmp_path: Path) -> None:
    """Verify failure message when custom executable path does not exist."""
    missing_bin = tmp_path / "non_existent_ffmpeg.exe"

    is_avail, desc = resolve_ffmpeg_status(str(missing_bin))
    assert not is_avail
    assert "not found" in desc.lower()


def test_validate_cookies_file_empty() -> None:
    """Verify empty or None cookie file path is considered valid (optional)."""
    is_valid, resolved = validate_cookies_file("")
    assert is_valid
    assert resolved == ""

    is_valid_none, resolved_none = validate_cookies_file(None)
    assert is_valid_none
    assert resolved_none == ""


def test_validate_cookies_file_valid(tmp_path: Path) -> None:
    """Verify valid existing cookie file passes validation."""
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n.tiktok.com\tTRUE\t/\tTRUE\t0\tttwid\t12345\n")

    is_valid, resolved = validate_cookies_file(str(cookie_file))
    assert is_valid
    assert Path(resolved).resolve() == cookie_file.resolve()


def test_validate_cookies_file_missing(tmp_path: Path) -> None:
    """Verify non-existent cookies file is rejected with clear error message."""
    missing = tmp_path / "missing_cookies.txt"
    is_valid, msg = validate_cookies_file(str(missing))
    assert not is_valid
    assert "not found" in msg.lower()


def test_validate_cookies_file_directory(tmp_path: Path) -> None:
    """Verify directory path is rejected when expecting cookie file."""
    cookie_dir = tmp_path / "cookie_folder"
    cookie_dir.mkdir()

    is_valid, msg = validate_cookies_file(str(cookie_dir))
    assert not is_valid
    assert "directory, not a file" in msg.lower()


def test_settings_repository_persistence(tmp_path: Path) -> None:
    """Verify keys are stored and retrieved from SQLite repository."""
    db_file = tmp_path / "test_settings.db"
    db_manager = DatabaseManager(db_path=db_file)
    repo = SettingsRepository(db_manager=db_manager)

    # Initially defaults
    assert repo.get(KEY_DOWNLOAD_DIR, "default_dir") == "default_dir"
    assert repo.get(KEY_MAX_CONCURRENT, "3") == "3"
    assert repo.get(KEY_FFMPEG_PATH, "") == ""
    assert repo.get(KEY_COOKIES_FILE, "") == ""
    assert repo.get(KEY_COOKIES_BROWSER, "") == ""

    # Set new values
    test_dir = str(tmp_path / "my_downloads")
    test_cookies = str(tmp_path / "my_cookies.txt")
    repo.set(KEY_DOWNLOAD_DIR, test_dir)
    repo.set(KEY_MAX_CONCURRENT, "5")
    repo.set(KEY_FFMPEG_PATH, "C:/tools/ffmpeg.exe")
    repo.set(KEY_COOKIES_FILE, test_cookies)
    repo.set(KEY_COOKIES_BROWSER, "chrome")

    # Read back
    assert repo.get(KEY_DOWNLOAD_DIR) == test_dir
    assert repo.get(KEY_MAX_CONCURRENT) == "5"
    assert repo.get(KEY_FFMPEG_PATH) == "C:/tools/ffmpeg.exe"
    assert repo.get(KEY_COOKIES_FILE) == test_cookies
    assert repo.get(KEY_COOKIES_BROWSER) == "chrome"
