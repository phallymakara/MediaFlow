"""Comprehensive security tests for SSRF, data redaction, boundaries, and validation."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from app.config import AppConfig
from app.core.download_worker import DownloadWorker
from app.core.downloader import Downloader
from app.core.tasks import DownloadTask
from app.database.database import DatabaseManager
from app.database.models import DownloadStatus
from app.database.repository import SettingsRepository
from app.services.license import LicenseService, LicenseStatus
from app.services.network import redact_url_for_logging, validate_outbound_url
from app.services.storage import StorageService


def test_validate_outbound_url_allowed_schemes() -> None:
    """Verify that public HTTP and HTTPS URLs pass validation."""
    assert validate_outbound_url("https://example.com/video.mp4") == "https://example.com/video.mp4"
    assert validate_outbound_url("http://subdomain.example.org/path") == "http://subdomain.example.org/path"


def test_validate_outbound_url_disallowed_schemes() -> None:
    """Verify that non-HTTP/HTTPS schemes are rejected."""
    with pytest.raises(ValueError, match="Disallowed URL scheme"):
        validate_outbound_url("file:///etc/passwd")

    with pytest.raises(ValueError, match="Disallowed URL scheme"):
        validate_outbound_url("ftp://ftp.example.com/resource")

    with pytest.raises(ValueError, match="Disallowed URL scheme"):
        validate_outbound_url("gopher://gopher.example.com")


def test_validate_outbound_url_loopback_and_metadata() -> None:
    """Verify that loopback, localhost, and cloud metadata targets are rejected."""
    with pytest.raises(ValueError, match="Access to private or restricted IP address"):
        validate_outbound_url("http://127.0.0.1:8080/secret")

    with pytest.raises(ValueError, match="Access to local or internal host"):
        validate_outbound_url("http://localhost:3000/api")

    with pytest.raises(ValueError, match="Access to private or restricted IP address"):
        validate_outbound_url("http://169.254.169.254/latest/meta-data/")


def test_validate_outbound_url_private_ip_ranges() -> None:
    """Verify that private RFC 1918 addresses are rejected."""
    with pytest.raises(ValueError, match="Access to private or restricted IP address"):
        validate_outbound_url("http://10.0.0.1/internal")

    with pytest.raises(ValueError, match="Access to private or restricted IP address"):
        validate_outbound_url("http://172.16.0.5/admin")

    with pytest.raises(ValueError, match="Access to private or restricted IP address"):
        validate_outbound_url("http://192.168.1.100/router")


def test_redact_url_for_logging() -> None:
    """Verify that query parameters and authentication credentials are stripped."""
    raw_url = "https://cdn.example.com/video.mp4?token=secret123&sig=abc456"
    redacted = redact_url_for_logging(raw_url)
    assert "token=secret123" not in redacted
    assert "sig=abc456" not in redacted
    assert redacted == "https://cdn.example.com/video.mp4"

    raw_with_auth = "https://user:password@secure.example.com/resource"
    redacted_auth = redact_url_for_logging(raw_with_auth)
    assert "password" not in redacted_auth
    assert "secure.example.com" in redacted_auth


def test_license_secret_key_length_validation() -> None:
    """Verify that secret keys under 16 characters are rejected."""
    with pytest.raises(ValueError, match="at least 16 characters"):
        LicenseService(secret_key="short_key")

    service = LicenseService(secret_key="adequate_secret_key_16_chars")
    assert service._secret == b"adequate_secret_key_16_chars"


def test_license_clock_tamper_detection_tightened(tmp_path: Path) -> None:
    """Verify clock tamper detection triggers on time rollback over 60 seconds."""
    db_file = tmp_path / "license_tamper.db"
    db_mgr = DatabaseManager(db_path=str(db_file))
    repo = SettingsRepository(db_manager=db_mgr)
    service = LicenseService(settings_repo=repo, secret_key="adequate_secret_key_16_chars")

    key = LicenseService.generate_key(
        expires_at=(datetime.now(timezone.utc) + timedelta(days=30)).date(),
        tier="pro",
        secret_key="adequate_secret_key_16_chars",
    )
    repo.set(LicenseService.SETTING_KEY_LICENSE, key)

    # Record a timestamp 120 seconds into the future
    future_iso = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()
    repo.set(LicenseService.SETTING_KEY_LAST_CHECK, future_iso)

    info = service.get_current_license()
    assert info.status == LicenseStatus.TAMPERED
    assert info.is_valid is False


def test_downloader_concurrency_clamping(tmp_path: Path) -> None:
    """Verify that concurrency is clamped between 1 and 20."""
    storage = StorageService(base_download_dir=tmp_path / "downloads")
    downloader = Downloader(max_concurrent=100, storage_service=storage)
    assert downloader.max_concurrent == 20

    downloader.set_max_concurrent(0)
    assert downloader.max_concurrent == 1

    downloader.set_max_concurrent(50)
    assert downloader.max_concurrent == 20

    downloader.shutdown()


def test_downloader_submit_sanitizes_title(tmp_path: Path) -> None:
    """Verify that path traversal in titles is neutralized on submission."""
    storage = StorageService(base_download_dir=tmp_path / "downloads")
    downloader = Downloader(max_concurrent=2, storage_service=storage)

    task = downloader.submit(
        url="https://example.com/media.mp4",
        title="../../system/evil:title",
        platform="generic",
    )

    assert ".." not in task.output_path.name
    assert ":" not in task.output_path.name
    assert ".." not in task.output_path.parent.name
    assert task.output_path.is_relative_to(storage.base_download_dir)


def test_downloader_submit_ssrf_rejection(tmp_path: Path) -> None:
    """Verify that submit rejects SSRF URLs immediately."""
    storage = StorageService(base_download_dir=tmp_path / "downloads")
    downloader = Downloader(max_concurrent=2, storage_service=storage)

    with pytest.raises(ValueError, match="Access to private or restricted IP address"):
        downloader.submit(
            url="http://127.0.0.1:8080/stream.mp4",
            title="Internal Stream",
            platform="generic",
        )

    downloader.shutdown()


def test_download_worker_content_type_validation(tmp_path: Path) -> None:
    """Verify that worker rejects non-media responses such as HTML."""
    storage = StorageService(base_download_dir=tmp_path / "downloads")
    task = DownloadTask(
        task_id="test_worker_ct",
        url="https://example.com/fake_video.mp4",
        title="Fake Video",
        platform="generic",
        output_path=storage.get_destination_path("fake.mp4"),
    )

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.headers = {"content-type": "text/html; charset=utf-8"}
    mock_response.raise_for_status = MagicMock()
    mock_client.stream.return_value.__enter__.return_value = mock_response

    worker = DownloadWorker(task=task, storage_service=storage, http_client=mock_client)
    result = worker.execute()

    assert result is None
    assert task.status == DownloadStatus.FAILED
    assert "not a valid media stream" in (task.error_message or "")


def test_download_worker_max_size_enforcement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that worker cancels download if stream exceeds maximum bytes."""
    storage = StorageService(base_download_dir=tmp_path / "downloads")
    task = DownloadTask(
        task_id="test_worker_size",
        url="https://example.com/oversized.mp4",
        title="Oversized Video",
        platform="generic",
        output_path=storage.get_destination_path("oversized.mp4"),
    )

    # Set tiny limit of 500 bytes for test
    mock_cfg = AppConfig(max_download_bytes=500)
    monkeypatch.setattr("app.core.download_worker.get_config", lambda: mock_cfg)

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.headers = {
        "content-type": "video/mp4",
        "content-length": "1000",
    }
    mock_response.raise_for_status = MagicMock()
    mock_client.stream.return_value.__enter__.return_value = mock_response

    worker = DownloadWorker(task=task, storage_service=storage, http_client=mock_client)
    result = worker.execute()

    assert result is None
    assert task.status == DownloadStatus.FAILED
    assert "maximum allowed" in (task.error_message or "").lower()


def test_production_config_enforces_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that production mode strictly requires a 16+ char license secret."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("MEDIAFLOW_LICENSE_SECRET", raising=False)

    with pytest.raises(ValueError, match="MEDIAFLOW_LICENSE_SECRET must be explicitly set"):
        AppConfig.from_env()

    monkeypatch.setenv("MEDIAFLOW_LICENSE_SECRET", "short")
    with pytest.raises(ValueError, match="at least 16 characters"):
        AppConfig.from_env()

    monkeypatch.setenv("MEDIAFLOW_LICENSE_SECRET", "valid_production_secret_key_12345")
    cfg = AppConfig.from_env()
    assert cfg.env == "production"
