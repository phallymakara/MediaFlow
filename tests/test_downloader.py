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


def test_task_pause_resume(tmp_path: Path) -> None:
    """Verify DownloadTask pause and resume behavior."""
    task = DownloadTask(
        task_id="task-pause-test",
        url="https://example.com/pause.mp4",
        title="Pause Test",
        platform="Direct",
        output_path=tmp_path / "pause.mp4",
        status=DownloadStatus.DOWNLOADING,
        speed_bytes_sec=1024 * 500,
    )

    assert task.is_paused is False
    assert task.status == DownloadStatus.DOWNLOADING

    # Pause task
    task.pause()
    assert task.is_paused is True
    assert task.status == DownloadStatus.PAUSED
    assert task.speed_bytes_sec == 0.0

    # Resume task
    task.resume()
    assert task.is_paused is False
    assert task.status == DownloadStatus.DOWNLOADING

    # Cancel unblocks paused state
    task.pause()
    assert task.is_paused is True
    task.cancel()
    assert task.is_paused is False
    assert task.is_cancelled is True
    task.set_status(DownloadStatus.CANCELLED)
    assert task.status == DownloadStatus.CANCELLED


def test_downloader_queue_controls(tmp_path: Path) -> None:
    """Verify Downloader pause_all, resume_all, and cancel_all queue management."""
    downloader = Downloader(max_concurrent=5)

    task1 = DownloadTask(
        task_id="t1",
        url="https://example.com/1.mp4",
        title="T1",
        platform="Direct",
        output_path=tmp_path / "1.mp4",
        status=DownloadStatus.DOWNLOADING,
    )
    task2 = DownloadTask(
        task_id="t2",
        url="https://example.com/2.mp4",
        title="T2",
        platform="Direct",
        output_path=tmp_path / "2.mp4",
        status=DownloadStatus.QUEUED,
    )

    with downloader._lock:
        downloader._tasks["t1"] = task1
        downloader._tasks["t2"] = task2

    # Pause all
    paused_count = downloader.pause_all()
    assert paused_count == 2
    assert task1.status == DownloadStatus.PAUSED
    assert task2.status == DownloadStatus.PAUSED
    assert len(downloader.get_active_tasks()) == 2

    # Resume all
    resumed_count = downloader.resume_all()
    assert resumed_count == 2
    assert task1.status == DownloadStatus.DOWNLOADING
    assert task2.status == DownloadStatus.DOWNLOADING

    # Individual pause / resume
    assert downloader.pause("t1") is True
    assert task1.status == DownloadStatus.PAUSED
    assert downloader.resume("t1") is True
    assert task1.status == DownloadStatus.DOWNLOADING

    # Cancel all
    cancelled_count = downloader.cancel_all()
    assert cancelled_count == 2
    assert task1.is_cancelled is True
    assert task2.is_cancelled is True

    downloader.shutdown(wait=False)


def test_downloader_auto_subfolder_creation(tmp_path: Path) -> None:
    """Verify submit auto-creates folder with title and datetime inside base_download_dir."""
    dl_dir = tmp_path / "custom_videos"
    storage = StorageService(base_download_dir=dl_dir)
    downloader = Downloader(storage_service=storage)

    task = downloader.submit(
        url="https://example.com/movie.mp4",
        title="Epic Adventure Movie",
        platform="Direct",
    )

    # Output path must be inside a dedicated subfolder of dl_dir
    assert task.output_path.parent != dl_dir
    assert task.output_path.parent.parent == dl_dir
    assert task.output_path.parent.name.startswith("Epic_Adventure_Movie_")
    assert task.output_path.parent.is_dir()
    assert task.output_path.name == "Epic_Adventure_Movie.mp4"

    downloader.shutdown(wait=False)


def test_downloader_explicit_subfolder_grouping(tmp_path: Path) -> None:
    """Verify multiple episodes with a shared subfolder are grouped in the same directory."""
    dl_dir = tmp_path / "drama_downloads"
    storage = StorageService(base_download_dir=dl_dir)
    downloader = Downloader(storage_service=storage)

    session_folder = "The_Lost_CEO_2026-09-24_12-00-00"

    task_ep1 = downloader.submit(
        url="https://example.com/ep1.mp4",
        title="The Lost CEO - Ep 01",
        platform="DramaBox",
        subfolder=session_folder,
    )

    task_ep2 = downloader.submit(
        url="https://example.com/ep2.mp4",
        title="The Lost CEO - Ep 02",
        platform="DramaBox",
        subfolder=session_folder,
    )

    # Both episodes must share the exact same subfolder
    assert task_ep1.output_path.parent == dl_dir / session_folder
    assert task_ep2.output_path.parent == dl_dir / session_folder
    assert task_ep1.output_path.parent == task_ep2.output_path.parent
    assert task_ep1.output_path.name == "The_Lost_CEO_-_Ep_01.mp4"
    assert task_ep2.output_path.name == "The_Lost_CEO_-_Ep_02.mp4"

    downloader.shutdown(wait=False)


def test_download_worker_tiktok_auth_error_message(tmp_path: Path) -> None:
    """Verify TikTok IP block / login error produces actionable user guidance."""
    task = DownloadTask(
        task_id="tiktok-task-1",
        url="https://www.tiktok.com/@destinystonedrama/video/7675414926252379413",
        title="Thần Y Hạ Sơn",
        platform="TikTok",
        output_path=tmp_path / "tiktok_test.mp4",
    )
    storage = StorageService(base_download_dir=tmp_path)
    worker = DownloadWorker(task=task, storage_service=storage)

    # Simulate TikTok 10204 / IP block error
    tiktok_exc = Exception("ERROR: [TikTok] 7675414926252379413: Your IP address is blocked from accessing this post")
    worker._handle_failure(None, tiktok_exc)

    assert task.status == DownloadStatus.FAILED
    assert "cookies.txt" in task.error_message
    assert "Settings" in task.error_message




