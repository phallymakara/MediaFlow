"""Asynchronous and background task worker structures."""

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from app.database.models import DownloadStatus

logger = logging.getLogger(__name__)


@dataclass
class DownloadTask:
    """Encapsulates the state, metrics, and lifecycle of a media download job."""

    task_id: str
    url: str
    title: str
    platform: str
    output_path: Path
    format_id: Optional[str] = None
    quality: Optional[str] = None
    status: DownloadStatus = DownloadStatus.QUEUED
    downloaded_bytes: int = 0
    total_bytes: int = 0
    speed_bytes_sec: float = 0.0
    eta_seconds: Optional[int] = None
    error_message: Optional[str] = None

    cancel_event: threading.Event = field(default_factory=threading.Event)
    pause_event: threading.Event = field(default_factory=threading.Event)
    on_progress: Optional[Callable[["DownloadTask"], None]] = None
    on_status_change: Optional[Callable[["DownloadTask", DownloadStatus, DownloadStatus], None]] = None

    @property
    def progress_percentage(self) -> float:
        """Return download completion percentage between 0.0 and 100.0."""
        if self.total_bytes > 0:
            return min(100.0, (self.downloaded_bytes / self.total_bytes) * 100.0)
        return 0.0

    @property
    def is_cancelled(self) -> bool:
        """Return True if cancellation has been requested."""
        return self.cancel_event.is_set()

    @property
    def is_paused(self) -> bool:
        """Return True if pause has been requested."""
        return self.pause_event.is_set()

    def update_progress(
        self,
        downloaded_bytes: int,
        total_bytes: Optional[int] = None,
        speed: Optional[float] = None,
        eta: Optional[int] = None,
    ) -> None:
        """Update download metrics and trigger progress listener.

        Args:
            downloaded_bytes: Current bytes transferred.
            total_bytes: Total file size in bytes.
            speed: Speed in bytes per second.
            eta: Estimated seconds remaining.
        """
        self.downloaded_bytes = downloaded_bytes
        if total_bytes and total_bytes > 0:
            self.total_bytes = total_bytes
        if speed is not None:
            self.speed_bytes_sec = speed
        if eta is not None:
            self.eta_seconds = eta

        if self.on_progress:
            try:
                self.on_progress(self)
            except Exception as exc:
                logger.error("Error in on_progress callback: %s", exc)

    def set_status(
        self,
        new_status: DownloadStatus,
        error_message: Optional[str] = None,
    ) -> None:
        """Transition task status and notify listeners.

        Args:
            new_status: Target DownloadStatus.
            error_message: Optional error message if state is FAILED.
        """
        old_status = self.status
        self.status = new_status
        if error_message:
            self.error_message = error_message

        logger.debug(
            "Task %s status transition: %s -> %s",
            self.task_id,
            old_status.value,
            new_status.value,
        )

        if self.on_status_change and old_status != new_status:
            try:
                self.on_status_change(self, old_status, new_status)
            except Exception as exc:
                logger.error("Error in on_status_change callback: %s", exc)

    def pause(self) -> None:
        """Signal this task to pause download execution."""
        if self.status in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING):
            self.pause_event.set()
            self.speed_bytes_sec = 0.0
            self.set_status(DownloadStatus.PAUSED)
            logger.info("Task %s paused", self.task_id)

    def resume(self) -> None:
        """Resume execution of this paused task."""
        if self.is_paused or self.status == DownloadStatus.PAUSED:
            self.pause_event.clear()
            self.set_status(DownloadStatus.DOWNLOADING)
            logger.info("Task %s resumed", self.task_id)

    def cancel(self) -> None:
        """Request cooperative cancellation of this download."""
        self.cancel_event.set()
        self.pause_event.clear()  # Ensure paused worker unblocks to complete cancellation
        self.speed_bytes_sec = 0.0
        logger.info("Cancellation requested for task %s", self.task_id)

