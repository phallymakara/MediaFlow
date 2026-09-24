"""End-to-end integration test validating features from Step 1 through Step 6."""

import time
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from app.config import get_config
from app.core.downloader import Downloader
from app.core.extractor_registry import get_default_registry
from app.database.database import DatabaseManager
from app.database.models import DownloadStatus
from app.database.repository import DownloadRepository, SettingsRepository
from app.extractors.dramabox import DramaBoxExtractor
from app.extractors.ytdlp import YtDlpExtractor
from app.services.ffmpeg import FFmpegService
from app.services.metadata import MetadataService
from app.services.storage import StorageService


def test_complete_pipeline_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate full end-to-end flow: config -> registry -> extraction -> storage -> download -> persistence."""

    # 1. Step 1: Configuration
    config = get_config()
    assert config is not None
    assert config.env in ("development", "production", "test")

    # 2. Step 2: Storage & Metadata
    download_dir = tmp_path / "downloads"
    temp_dir = tmp_path / "temp"
    storage = StorageService(base_download_dir=download_dir, temp_dir=temp_dir)
    assert storage.base_download_dir.exists()
    assert storage.temp_dir.exists()

    clean_title = MetadataService.clean_title("The Lost CEO &amp; Heiress: Episode 1")
    assert clean_title == "The Lost CEO & Heiress: Episode 1"

    sanitized_filename = storage.sanitize_filename(f"{clean_title}.mp4")
    assert ":" not in sanitized_filename
    assert "&" in sanitized_filename

    formatted_size = MetadataService.format_bytes(10485760)
    assert formatted_size == "10.00 MB"

    ffmpeg = FFmpegService()
    # Binary detection runs safely without exceptions
    assert isinstance(ffmpeg.is_available(), bool)

    # 3. Step 3: Persistence Layer
    db = DatabaseManager(":memory:")
    repo = DownloadRepository(db)
    settings = SettingsRepository(db)

    settings.set("download_dir", str(download_dir))
    assert settings.get("download_dir") == str(download_dir)

    # 4. Step 4 & 5: Extractor Registry & Platform Routing
    registry = get_default_registry()

    # Verify mainstream routing to YtDlpExtractor
    yt_extractor = registry.find_extractor("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert isinstance(yt_extractor, YtDlpExtractor)

    # Verify short drama routing to DramaBoxExtractor
    drama_extractor = registry.find_extractor("https://www.dramabox.com/watch/drama-99")
    assert isinstance(drama_extractor, DramaBoxExtractor)

    # 5. Step 6: Download Engine & Atomic Staging
    downloader = Downloader(
        max_concurrent=2,
        storage_service=storage,
        ffmpeg_service=ffmpeg,
        repository=repo,
    )

    mock_client = MagicMock(spec=httpx.Client)
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.headers = {"content-length": "46"}
    mock_resp.iter_bytes.return_value = [b"video_data_chunk_part1_", b"video_data_chunk_part2_"]
    mock_client.stream.return_value.__enter__.return_value = mock_resp

    # Intercept any background worker HTTP clients
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: mock_client)

    progress_events = []

    def on_prog(task):
        progress_events.append(task.downloaded_bytes)

    # Submit task
    task = downloader.submit(
        url="https://example.com/direct/video.mp4",
        title="Integration Test Video",
        platform="Direct",
        on_progress=on_prog,
    )

    assert task.task_id is not None

    # Verify task was recorded in SQLite
    db_record = repo.get_by_id(task.task_id)
    assert db_record is not None
    assert db_record.title == "Integration Test Video"

    # Execute worker with mocked stream to verify pipeline completion
    from app.core.download_worker import DownloadWorker

    worker = DownloadWorker(
        task=task,
        storage_service=storage,
        ffmpeg_service=ffmpeg,
        repository=repo,
        http_client=mock_client,
    )

    completed_path = worker.execute()
    assert completed_path is not None
    assert completed_path.exists()
    assert completed_path.read_bytes() == b"video_data_chunk_part1_video_data_chunk_part2_"

    # Verify final status in task and database
    assert task.status == DownloadStatus.COMPLETED
    final_db_record = repo.get_by_id(task.task_id)
    assert final_db_record.status == DownloadStatus.COMPLETED
    assert final_db_record.downloaded_bytes == 46

    # 6. Cancellation Pipeline Verification
    cancel_task = downloader.submit(
        url="https://example.com/direct/cancel.mp4",
        title="Cancel Test Video",
        platform="Direct",
    )

    cancel_worker = DownloadWorker(
        task=cancel_task,
        storage_service=storage,
        repository=repo,
        http_client=mock_client,
    )

    cancel_task.cancel()
    result = cancel_worker.execute()
    assert result is None
    assert cancel_task.status == DownloadStatus.CANCELLED

    cancelled_db_record = repo.get_by_id(cancel_task.task_id)
    assert cancelled_db_record.status == DownloadStatus.CANCELLED

    downloader.shutdown(wait=False)
