"""Download execution and lifecycle management."""

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Optional

from app.config import get_config
from app.core.download_worker import DownloadWorker
from app.core.tasks import DownloadTask
from app.database.models import DownloadRecord, DownloadStatus
from app.database.repository import DownloadRepository
from app.services.ffmpeg import FFmpegService
from app.services.storage import StorageService

logger = logging.getLogger(__name__)


class Downloader:
    """Manages active downloads, concurrency, progress events, and cancellations."""

    def __init__(
        self,
        max_concurrent: Optional[int] = None,
        storage_service: Optional[StorageService] = None,
        ffmpeg_service: Optional[FFmpegService] = None,
        repository: Optional[DownloadRepository] = None,
    ) -> None:
        """Initialize download manager with services and worker pool."""
        config = get_config()
        self.max_concurrent = max(1, max_concurrent or config.max_concurrent_downloads)
        self.storage = storage_service or StorageService()
        self.ffmpeg = ffmpeg_service
        self.repo = repository

        self._tasks: Dict[str, DownloadTask] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_concurrent,
            thread_name_prefix="MediaFlowWorker",
        )

        logger.info("Downloader initialized with max_concurrent=%d", self.max_concurrent)

    def submit(
        self,
        url: str,
        title: str,
        platform: str,
        output_path: Optional[Path] = None,
        format_id: Optional[str] = None,
        quality: Optional[str] = None,
        thumbnail_url: Optional[str] = None,
        on_progress: Optional[Callable[[DownloadTask], None]] = None,
        on_status_change: Optional[Callable[[DownloadTask, DownloadStatus, DownloadStatus], None]] = None,
    ) -> DownloadTask:
        """Enqueue a new download task.

        Args:
            url: Source media URL.
            title: Title of the media.
            platform: Platform name string.
            output_path: Target destination path on disk.
            format_id: Format identifier.
            quality: Quality label.
            thumbnail_url: Preview thumbnail link.
            on_progress: Progress callback listener.
            on_status_change: Status transition listener.

        Returns:
            The created and queued DownloadTask instance.
        """
        task_id = str(uuid.uuid4())

        # Determine target file path if not explicitly provided
        if output_path is None:
            clean_filename = f"{title}.mp4"
            dest_candidate = self.storage.get_destination_path(clean_filename)
            output_path = self.storage.get_unique_destination_path(dest_candidate)

        task = DownloadTask(
            task_id=task_id,
            url=url,
            title=title,
            platform=platform,
            output_path=output_path,
            format_id=format_id,
            quality=quality,
            status=DownloadStatus.QUEUED,
            on_progress=on_progress,
            on_status_change=on_status_change,
        )

        with self._lock:
            self._tasks[task_id] = task

        # Persist task to database if repository is configured
        if self.repo:
            try:
                record = DownloadRecord(
                    task_id=task.task_id,
                    url=task.url,
                    title=task.title,
                    platform=task.platform,
                    output_path=str(task.output_path),
                    thumbnail_url=thumbnail_url,
                    file_format=output_path.suffix.lstrip("."),
                    quality=quality,
                    status=DownloadStatus.QUEUED,
                )
                self.repo.add(record)
            except Exception as exc:
                logger.error("Failed to persist initial download record: %s", exc)

        worker = DownloadWorker(
            task=task,
            storage_service=self.storage,
            ffmpeg_service=self.ffmpeg,
            repository=self.repo,
        )

        self._executor.submit(worker.execute)
        logger.info("Queued download task %s for '%s'", task_id, title)
        return task

    def cancel(self, task_id: str) -> bool:
        """Cancel an active or queued download task by ID.

        Args:
            task_id: Task UUID.

        Returns:
            True if task was located and cancellation signalled.
        """
        task = self.get_task(task_id)
        if task:
            task.cancel()
            return True
        return False

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        """Retrieve in-memory task by ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def get_active_tasks(self) -> List[DownloadTask]:
        """Return list of active, downloading, or processing tasks."""
        active_statuses = (
            DownloadStatus.QUEUED,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.PROCESSING,
        )
        with self._lock:
            return [t for t in self._tasks.values() if t.status in active_statuses]

    def get_all_tasks(self) -> List[DownloadTask]:
        """Return all in-memory tasks."""
        with self._lock:
            return list(self._tasks.values())

    def set_max_concurrent(self, limit: int) -> None:
        """Dynamically update maximum concurrent worker pool capacity.

        Args:
            limit: New maximum concurrent tasks (minimum 1).
        """
        self.max_concurrent = max(1, limit)
        old_executor = self._executor
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_concurrent,
            thread_name_prefix="MediaFlowWorker",
        )
        old_executor.shutdown(wait=False)
        logger.info("Updated worker concurrency to %d", self.max_concurrent)

    def shutdown(self, wait: bool = False) -> None:
        """Cancel running tasks and shut down worker pool."""
        logger.info("Shutting down downloader pool...")
        with self._lock:
            for task in self._tasks.values():
                if task.status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING):
                    task.cancel()
        self._executor.shutdown(wait=wait)

