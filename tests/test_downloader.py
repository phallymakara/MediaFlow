"""Tests for core download manager, worker, and task models."""

import time
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from app.core.download_worker import DownloadWorker
from app.core.downloader import Downloader
from app.core.tasks import DownloadTask
from app.database.database import DatabaseManager
from app.database.models import DownloadStatus
from app.database.repository import DownloadRepository
from app.services.storage import StorageService


def test_task_properties_and_progress_percentage(tmp_path: Path) -> None:
    """Verify DownloadTask metric calculations and percentage helper."""
    task = DownloadTask(
        task_id="task-1",
        url="https://example.com/video.mp4",
        title="Test Video",
        platform="Test",
        output_path=tmp_path / "test.mp4",
        total_bytes=1000,
        downloaded_bytes=250,
    )

    assert task.progress_percentage == 25.0
    assert task.is_cancelled is False

    task.update_progress(downloaded_bytes=750, total_bytes=1000)
    assert task.progress_percentage == 75.0

    task.cancel()
    assert task.is_cancelled is True


def test_task_callbacks(tmp_path: Path) -> None:
    """Verify progress and status callbacks fire properly."""
    progress_called = []
    status_called = []

    def on_prog(t: DownloadTask) -> None:
        progress_called.append(t.downloaded_bytes)

    def on_stat(t: DownloadTask, old_s: DownloadStatus, new_s: DownloadStatus) -> None:
        status_called.append((old_s, new_s))

    task = DownloadTask(
        task_id="task-2",
        url="https://example.com/v.mp4",
        title="V",
        platform="P",
        output_path=tmp_path / "v.mp4",
        on_progress=on_prog,
        on_status_change=on_stat,
    )

    task.update_progress(500)
    assert progress_called == [500]

    task.set_status(DownloadStatus.DOWNLOADING)
    assert status_called == [(DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING)]


def test_worker_direct_stream_mocked(tmp_path: Path) -> None:
    """Verify DownloadWorker downloads stream chunks and atomically commits file."""
    dl_dir = tmp_path / "downloads"
    storage = StorageService(base_download_dir=dl_dir)

    target_file = dl_dir / "stream_video.mp4"
    task = DownloadTask(
        task_id="worker-task-1",
        url="https://example.com/stream_video.mp4",
        title="Stream Video",
        platform="Direct",
        output_path=target_file,
    )

    mock_client = MagicMock(spec=httpx.Client)
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.headers = {"content-length": "12"}
    mock_resp.iter_bytes.return_value = [b"hello ", b"world!"]

    # Context manager mock for client.stream("GET", ...)
    mock_client.stream.return_value.__enter__.return_value = mock_resp

    worker = DownloadWorker(
        task=task,
        storage_service=storage,
        http_client=mock_client,
    )

    result_path = worker.execute()

    assert result_path == target_file
    assert target_file.exists()
    assert target_file.read_bytes() == b"hello world!"
    assert task.status == DownloadStatus.COMPLETED
    assert task.downloaded_bytes == 12


def test_worker_cancellation_cleans_up(tmp_path: Path) -> None:
    """Verify cancelled worker cleans up temporary files and sets CANCELLED status."""
    dl_dir = tmp_path / "downloads"
    storage = StorageService(base_download_dir=dl_dir)

    target_file = dl_dir / "cancelled_video.mp4"
    task = DownloadTask(
        task_id="worker-task-cancel",
        url="https://example.com/cancelled_video.mp4",
        title="Cancelled Video",
        platform="Direct",
        output_path=target_file,
    )

    mock_client = MagicMock(spec=httpx.Client)
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.headers = {"content-length": "1000"}

    def iter_with_cancel(chunk_size: int):
        yield b"chunk1"
        task.cancel()
        yield b"chunk2"

    mock_resp.iter_bytes.side_effect = iter_with_cancel
    mock_client.stream.return_value.__enter__.return_value = mock_resp

    worker = DownloadWorker(
        task=task,
        storage_service=storage,
        http_client=mock_client,
    )

    result = worker.execute()
    assert result is None
    assert task.status == DownloadStatus.CANCELLED
    assert not target_file.exists()

    # Verify no temp files remain
    temp_files = list(storage.temp_dir.glob("worker-task-cancel*"))
    assert len(temp_files) == 0


def test_downloader_submit_and_cancel(tmp_path: Path) -> None:
    """Verify Downloader queueing, tracking, and cancellation."""
    storage = StorageService(base_download_dir=tmp_path)
    downloader = Downloader(max_concurrent=2, storage_service=storage)

    task = downloader.submit(
        url="https://example.com/item.mp4",
        title="Queued Item",
        platform="TestPlatform",
    )

    assert task.task_id is not None
    assert downloader.get_task(task.task_id) is task

    assert downloader.cancel(task.task_id) is True
    assert task.is_cancelled is True

    downloader.shutdown(wait=False)


def test_downloader_sync_with_repository(tmp_path: Path) -> None:
    """Verify Downloader synchronizes task lifecycle with SQLite database."""
    storage = StorageService(base_download_dir=tmp_path)
    db = DatabaseManager(":memory:")
    repo = DownloadRepository(db)

    downloader = Downloader(
        max_concurrent=2,
        storage_service=storage,
        repository=repo,
    )

    task = downloader.submit(
        url="https://example.com/sample.mp4",
        title="Sample Video",
        platform="Direct",
    )

    # Initial record created in SQLite and tracked across states
    record = repo.get_by_id(task.task_id)
    assert record is not None
    assert record.title == "Sample Video"
    assert record.status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING, DownloadStatus.FAILED)

    downloader.shutdown(wait=False)


def test_downloader_concurrency_adjustment(tmp_path: Path) -> None:
    """Verify dynamic update of worker concurrency limit."""
    downloader = Downloader(max_concurrent=3)
    assert downloader.max_concurrent == 3

    downloader.set_max_concurrent(6)
    assert downloader.max_concurrent == 6

    downloader.set_max_concurrent(0)  # Should enforce minimum 1
    assert downloader.max_concurrent == 1

    downloader.shutdown(wait=False)


def test_resolve_ytdlp_format() -> None:
    """Verify format resolution mappings and resilient fallbacks."""
    from app.core.download_worker import resolve_ytdlp_format

    assert resolve_ytdlp_format(None) == "bestvideo+bestaudio/best"
    assert resolve_ytdlp_format("") == "bestvideo+bestaudio/best"
    assert resolve_ytdlp_format("Best Quality (Auto)") == "bestvideo+bestaudio/best"
    assert "1080" in resolve_ytdlp_format("1080p MP4")
    assert "/bestvideo+bestaudio/best" in resolve_ytdlp_format("1080p MP4")
    assert "720" in resolve_ytdlp_format("720p")
    assert resolve_ytdlp_format("Audio Only (MP3)") == "bestaudio/best"
    assert resolve_ytdlp_format("mp3") == "bestaudio/best"
    # Complex existing selector preserved
    assert resolve_ytdlp_format("bestvideo[height<=720]+bestaudio/best") == "bestvideo[height<=720]+bestaudio/best"


