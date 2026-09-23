"""Tests for asynchronous GUI workers and Qt signal bridge."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
from PySide6.QtCore import QCoreApplication

from app.core.media import MediaFormat, MediaInfo
from app.core.tasks import DownloadTask
from app.database.models import DownloadStatus
from app.gui.workers import AnalyzeWorker, DownloadSignalBridge


@pytest.fixture(scope="session")
def qapp() -> QCoreApplication:
    """Fixture providing a QCoreApplication instance."""
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_analyze_worker_success(qapp: QCoreApplication) -> None:
    """Verify AnalyzeWorker resolves metadata and emits analysis_success."""
    mock_registry = MagicMock()
    mock_metadata = MediaInfo(
        url="https://example.com/watch?v=123",
        title="Sample Video",
        platform="youtube",
        formats=[MediaFormat(format_id="best", resolution="1080p", extension="mp4")],
    )
    mock_registry.extract.return_value = mock_metadata

    worker = AnalyzeWorker(url="https://example.com/watch?v=123", extractor_registry=mock_registry)

    success_payload = []
    error_payload = []

    worker.analysis_success.connect(lambda meta: success_payload.append(meta))
    worker.analysis_failed.connect(lambda err: error_payload.append(err))

    # Run worker synchronously for test
    worker.run()

    assert len(success_payload) == 1
    assert success_payload[0].title == "Sample Video"
    assert len(error_payload) == 0


def test_analyze_worker_ssrf_rejection(qapp: QCoreApplication) -> None:
    """Verify AnalyzeWorker rejects loopback and internal network addresses."""
    mock_registry = MagicMock()
    worker = AnalyzeWorker(url="http://127.0.0.1:8080/internal.mp4", extractor_registry=mock_registry)

    error_payload = []
    worker.analysis_failed.connect(lambda err: error_payload.append(err))

    worker.run()

    assert len(error_payload) == 1
    assert "restricted" in error_payload[0].lower()
    mock_registry.extract.assert_not_called()


def test_analyze_worker_extraction_error(qapp: QCoreApplication) -> None:
    """Verify AnalyzeWorker catches extraction failures and emits safe message."""
    mock_registry = MagicMock()
    mock_registry.extract.side_effect = RuntimeError("Network socket timed out")

    worker = AnalyzeWorker(url="https://example.com/video.mp4", extractor_registry=mock_registry)

    error_payload = []
    worker.analysis_failed.connect(lambda err: error_payload.append(err))

    worker.run()

    assert len(error_payload) == 1
    assert "unable to extract media" in error_payload[0].lower()
    assert "socket timed out" not in error_payload[0]  # Technical error hidden


def test_download_signal_bridge_progress(qapp: QCoreApplication) -> None:
    """Verify DownloadSignalBridge captures progress and emits Qt signal."""
    bridge = DownloadSignalBridge()

    emitted_progress = []
    bridge.progress_updated.connect(
        lambda tid, dl, total, spd, eta, pct: emitted_progress.append((tid, dl, total, spd, eta, pct))
    )

    task = DownloadTask(
        task_id="task-123",
        url="https://example.com/media.mp4",
        title="Test Media",
        platform="generic",
        output_path=Path("downloads/test.mp4"),
    )
    task.update_progress(downloaded_bytes=5000, total_bytes=10000, speed=1000.0, eta=5)

    bridge.on_progress(task)

    assert len(emitted_progress) == 1
    task_id, dl, total, spd, eta, pct = emitted_progress[0]
    assert task_id == "task-123"
    assert dl == 5000
    assert total == 10000
    assert spd == 1000.0
    assert eta == 5
    assert pct == 50


def test_download_signal_bridge_status_change(qapp: QCoreApplication) -> None:
    """Verify DownloadSignalBridge emits status changes and completion signal."""
    bridge = DownloadSignalBridge()

    status_events = []
    completion_events = []

    bridge.status_changed.connect(lambda tid, stat, err: status_events.append((tid, stat, err)))
    bridge.task_completed.connect(lambda tid, path: completion_events.append((tid, path)))

    task = DownloadTask(
        task_id="task-completed",
        url="https://example.com/done.mp4",
        title="Done Media",
        platform="generic",
        output_path=Path("downloads/done.mp4"),
    )

    bridge.on_status_change(task, DownloadStatus.DOWNLOADING, DownloadStatus.COMPLETED)

    assert len(status_events) == 1
    assert status_events[0] == ("task-completed", "completed", "")

    assert len(completion_events) == 1
    assert completion_events[0][0] == "task-completed"
    assert "done.mp4" in completion_events[0][1]
