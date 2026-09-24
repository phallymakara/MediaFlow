"""Tests for DownloaderPage formatting, helpers, and episode selection logic."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from app.core.media import MediaEpisode, MediaInfo
from app.database.models import DownloadStatus
from app.gui.downloader_page import format_bytes, format_eta, format_speed, format_speed_eta


def test_format_bytes() -> None:
    """Verify human-readable file size formatting."""
    assert format_bytes(0) == "--"
    assert format_bytes(-5) == "--"
    assert format_bytes(512) == "512.0 B"
    assert format_bytes(1024 * 25) == "25.0 KB"
    assert format_bytes(1024 * 1024 * 142) == "142.0 MB"
    assert format_bytes(int(1024 * 1024 * 1024 * 2.5)) == "2.5 GB"


def test_format_speed() -> None:
    """Verify download speed string formatting."""
    assert format_speed(0.0) == "--"
    assert format_speed(-10.0) == "--"
    assert format_speed(1024 * 80) == "80.0 KB/s"
    assert format_speed(1024 * 1024 * 8.6) == "8.6 MB/s"


def test_format_eta() -> None:
    """Verify remaining duration ETA formatting."""
    assert format_eta(None) == "--"
    assert format_eta(0) == "--"
    assert format_eta(24) == "24s"
    assert format_eta(75) == "1m 15s"
    assert format_eta(3665) == "1h 01m"


def test_format_speed_eta() -> None:
    """Verify combined Speed and ETA label formatting."""
    assert format_speed_eta(0.0, None) == "--"
    assert format_speed_eta(0.0, 45) == "--"
    assert format_speed_eta(1024 * 1024 * 5.2, None) == "5.2 MB/s"
    assert format_speed_eta(1024 * 1024 * 5.2, 45) == "5.2 MB/s • 45s left"
    assert format_speed_eta(1024 * 500, 75) == "500.0 KB/s • 1m 15s left"


def test_media_episode_selection_logic() -> None:
    """Verify episode data structure and filtering for drama series."""
    episodes = [
        MediaEpisode(episode_number=1, title="Episode 1", url="https://example.com/ep1"),
        MediaEpisode(episode_number=2, title="Episode 2", url="https://example.com/ep2"),
        MediaEpisode(episode_number=3, title="Episode 3", url="https://example.com/ep3"),
    ]

    media_info = MediaInfo(
        url="https://example.com/series",
        title="Drama Series",
        platform="dramabox",
        episodes=episodes,
        is_playlist=True,
    )

    assert len(media_info.episodes) == 3
    assert media_info.is_playlist is True

    # Filter selection simulation
    selected = [ep for ep in media_info.episodes if ep.episode_number in (1, 3)]
    assert len(selected) == 2
    assert selected[0].episode_number == 1
    assert selected[1].episode_number == 3


def test_downloader_page_queue_controls(tmp_path: Path) -> None:
    """Verify Active Downloads toolbar buttons and pause/stop functionality."""
    from PySide6.QtWidgets import QApplication
    from app.core.downloader import Downloader
    from app.core.tasks import DownloadTask
    from app.gui.downloader_page import DownloaderPage

    app = QApplication.instance() or QApplication([])
    downloader = Downloader()
    page = DownloaderPage(downloader=downloader)

    assert page._pause_resume_all_btn is not None
    assert page._stop_all_btn is not None
    assert page._clear_finished_btn is not None
    assert page._pause_resume_all_btn.isEnabled() is False
    assert page._stop_all_btn.isEnabled() is False

    task = DownloadTask(
        task_id="t1",
        url="https://example.com/v.mp4",
        title="Test V",
        platform="youtube",
        output_path=tmp_path / "v.mp4",
        status=DownloadStatus.DOWNLOADING,
    )
    with downloader._lock:
        downloader._tasks["t1"] = task

    page._add_table_row(task)
    page._update_queue_summary()

    assert page._pause_resume_all_btn.isEnabled() is True
    assert page._stop_all_btn.isEnabled() is True
    assert page._pause_resume_all_btn.text() == "Pause All"

    # Toggle pause all
    page._toggle_pause_resume_all()
    assert task.status == DownloadStatus.PAUSED
    page._on_status_changed("t1", DownloadStatus.PAUSED.value, "")
    assert page._pause_resume_all_btn.text() == "Resume All"

    # Toggle resume all
    page._toggle_pause_resume_all()
    assert task.status == DownloadStatus.DOWNLOADING
    page._on_status_changed("t1", DownloadStatus.DOWNLOADING.value, "")
    assert page._pause_resume_all_btn.text() == "Pause All"

    # Stop all
    page._stop_all_tasks()
    assert task.is_cancelled is True
    downloader.shutdown(wait=False)


def test_media_loading_dialog_flow(tmp_path: Path) -> None:
    """Verify MediaLoadingDialog popup appearance, cancel interaction, and enqueue on resolution."""
    from PySide6.QtWidgets import QApplication, QLabel, QProgressBar
    from app.core.downloader import Downloader
    from app.core.media import MediaInfo
    from app.gui.dialogs.loading_dialog import MediaLoadingDialog
    from app.gui.downloader_page import DownloaderPage

    app = QApplication.instance() or QApplication([])
    downloader = Downloader()
    mock_license = MagicMock()
    mock_license.is_download_allowed.return_value = True
    page = DownloaderPage(downloader=downloader, license_service=mock_license)

    # 1. Trigger add download with URL
    page._url_input.setText("https://youtube.com/watch?v=sample123")
    page._on_add_download_clicked()

    # Verify popup dialog was created and is visible
    assert page._loading_dialog is not None
    assert isinstance(page._loading_dialog, MediaLoadingDialog)
    assert page._loading_dialog.windowTitle() == "Analyzing Media"

    # Verify progress bar inside dialog is indeterminate
    pbar = page._loading_dialog.findChild(QProgressBar)
    assert pbar is not None
    assert pbar.minimum() == 0
    assert pbar.maximum() == 0

    # Verify table does NOT contain placeholder rows while analyzing in popup
    assert page._table.rowCount() == 0

    # 2. Simulate analysis success
    meta = MediaInfo(
        url="https://youtube.com/watch?v=sample123",
        title="Sample Video Title",
        platform="youtube",
    )
    page._on_analysis_success(meta)

    # Dialog must be dismissed and download task enqueued in table
    assert page._loading_dialog is None
    assert page._table.rowCount() == 1
    assert "Sample Video Title" in page._table.cellWidget(0, 0).findChildren(QLabel)[-1].text()

    # 3. Test cancellation flow
    page._url_input.setText("https://youtube.com/watch?v=sample456")
    page._on_add_download_clicked()
    assert page._loading_dialog is not None

    page._loading_dialog.reject()
    # Loading dialog is cleaned up and worker stopped
    assert page._loading_dialog is None
    downloader.shutdown(wait=False)


def test_downloader_page_analysis_creates_subfolder(tmp_path: Path) -> None:
    """Verify DownloaderPage enqueues tasks inside title and date-time subfolders."""
    from PySide6.QtWidgets import QApplication
    from app.core.downloader import Downloader
    from app.core.media import MediaInfo
    from app.gui.downloader_page import DownloaderPage
    from app.services.storage import StorageService

    app = QApplication.instance() or QApplication([])
    custom_dir = tmp_path / "Videos"
    storage = StorageService(base_download_dir=custom_dir)
    downloader = Downloader(storage_service=storage)
    page = DownloaderPage(downloader=downloader)

    meta = MediaInfo(
        url="https://youtube.com/watch?v=subfolder_test",
        title="My Special Video",
        platform="youtube",
    )
    page._on_analysis_success(meta)

    assert page._table.rowCount() == 1
    task_id = page._row_tasks[0]
    task = downloader.get_task(task_id)
    assert task is not None

    # Path must be nested inside custom_dir / My_Special_Video_<timestamp> /
    assert task.output_path.parent.parent == custom_dir
    assert task.output_path.parent.name.startswith("My_Special_Video_")
    assert task.output_path.name == "My_Special_Video.mp4"

    downloader.shutdown(wait=False)


