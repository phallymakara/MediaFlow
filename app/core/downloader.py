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
from app.services.network import redact_url_for_logging, validate_outbound_url
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
        self.max_concurrent = max(1, min(int(max_concurrent or config.max_concurrent_downloads), 20))
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
        subfolder: Optional[str] = None,
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
            subfolder: Optional subfolder inside base download directory. If None and output_path
                is not specified, an automatic subfolder containing title and datetime is generated.
            format_id: Format identifier.
            quality: Quality label.
            thumbnail_url: Preview thumbnail link.
            on_progress: Progress callback listener.
            on_status_change: Status transition listener.

        Returns:
            The created and queued DownloadTask instance.
        """
        validate_outbound_url(url)
        task_id = str(uuid.uuid4())

        # Determine target file path if not explicitly provided
        if output_path is None:
            safe_title = self.storage.sanitize_filename(title) or "media"
            clean_filename = f"{safe_title}.mp4"
            target_subfolder = subfolder if subfolder is not None else self.storage.generate_media_folder_name(title)
            dest_candidate = self.storage.get_destination_path(clean_filename, subfolder=target_subfolder)
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
                clean_thumb = thumbnail_url if thumbnail_url and not thumbnail_url.startswith("data:") and len(thumbnail_url) <= 1000 else None
                record = DownloadRecord(
                    task_id=task.task_id,
                    url=task.url,
                    title=task.title,
                    platform=task.platform,
                    output_path=str(task.output_path),
                    thumbnail_url=clean_thumb,
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
        logger.info(
            "Queued download task %s for '%s' (url=%s)",
            task_id,
            title,
            redact_url_for_logging(url),
        )
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

    def pause(self, task_id: str) -> bool:
        """Pause a specific active or queued task by ID.

        Args:
            task_id: Task UUID.

        Returns:
            True if task was found and paused.
        """
        task = self.get_task(task_id)
        if task:
            task.pause()
            return True
        return False

    def resume(self, task_id: str) -> bool:
        """Resume a specific paused task by ID.

        Args:
            task_id: Task UUID.

        Returns:
            True if task was found and resumed.
        """
        task = self.get_task(task_id)
        if task:
            task.resume()
            return True
        return False

    def pause_all(self) -> int:
        """Pause all active and queued download tasks.

        Returns:
            Number of tasks paused.
        """
        count = 0
        with self._lock:
            for task in self._tasks.values():
                if task.status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING):
                    task.pause()
                    count += 1
        logger.info("Paused %d active tasks", count)
        return count

    def resume_all(self) -> int:
        """Resume all paused download tasks.

        Returns:
            Number of tasks resumed.
        """
        count = 0
        with self._lock:
            for task in self._tasks.values():
                if task.status == DownloadStatus.PAUSED or task.is_paused:
                    task.resume()
                    count += 1
        logger.info("Resumed %d paused tasks", count)
        return count

    def cancel_all(self) -> int:
        """Cancel all active, queued, or paused download tasks.

        Returns:
            Number of tasks cancelled.
        """
        count = 0
        with self._lock:
            for task in self._tasks.values():
                if task.status in (
                    DownloadStatus.QUEUED,
                    DownloadStatus.DOWNLOADING,
                    DownloadStatus.PROCESSING,
                    DownloadStatus.PAUSED,
                ):
                    task.cancel()
                    count += 1
        logger.info("Cancelled %d active tasks", count)
        return count

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        """Retrieve in-memory task by ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def get_active_tasks(self) -> List[DownloadTask]:
        """Return list of active, downloading, processing, or paused tasks."""
        active_statuses = (
            DownloadStatus.QUEUED,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.PROCESSING,
            DownloadStatus.PAUSED,
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
            limit: New maximum concurrent tasks (clamped between 1 and 20).
        """
        self.max_concurrent = max(1, min(int(limit), 20))
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
                if task.status in (
                    DownloadStatus.QUEUED,
                    DownloadStatus.DOWNLOADING,
                    DownloadStatus.PAUSED,
                ):
                    task.cancel()
        self._executor.shutdown(wait=wait)

