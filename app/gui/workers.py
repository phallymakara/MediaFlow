"""Asynchronous worker threads and Qt signal bridges for MediaFlow GUI."""

import logging
from typing import Optional

import httpx
from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QImage

from app.core.extractor_registry import ExtractorRegistry, get_default_registry
from app.core.media import MediaInfo
from app.core.tasks import DownloadTask
from app.database.models import DownloadStatus
from app.extractors.base import ExtractionError
from app.services.network import redact_url_for_logging, validate_outbound_url

logger = logging.getLogger(__name__)


class AnalyzeWorker(QThread):
    """Background worker thread for asynchronous media extraction and metadata resolution."""

    analysis_started = Signal()
    analysis_success = Signal(object)  # MediaInfo
    analysis_failed = Signal(str)

    def __init__(
        self,
        url: str,
        extractor_registry: Optional[ExtractorRegistry] = None,
        parent: Optional[QObject] = None,
        placeholder_id: str = "",
    ) -> None:
        """Initialize analyze worker.

        Args:
            url: Source media link to extract.
            extractor_registry: Extractor registry instance.
            parent: Optional parent QObject.
            placeholder_id: Optional tracking identifier for UI placeholder row.
        """
        super().__init__(parent)
        self.url = url.strip()
        self.registry = extractor_registry or get_default_registry()
        self.placeholder_id = placeholder_id

    def run(self) -> None:
        """Execute URL validation and extraction on background thread."""
        self.analysis_started.emit()

        if not self.url:
            self.analysis_failed.emit("Please enter a media URL.")
            return

        try:
            validate_outbound_url(self.url)
        except ValueError as val_err:
            logger.warning("SSRF / Invalid URL rejected: %s", val_err)
            self.analysis_failed.emit("Invalid URL or address is restricted.")
            return

        try:
            logger.info("Starting background analysis for URL: %s", redact_url_for_logging(self.url))
            extract_fn = getattr(self.registry, "extract", None) or getattr(self.registry, "extract_info")
            metadata: MediaInfo = extract_fn(self.url)
            self.analysis_success.emit(metadata)
        except ExtractionError as ext_err:
            logger.warning("Extraction failed for URL %s: %s", redact_url_for_logging(self.url), ext_err)
            self.analysis_failed.emit(str(ext_err))
        except Exception as exc:
            logger.error("Analysis failed for URL %s: %s", redact_url_for_logging(self.url), exc)
            self.analysis_failed.emit("Unable to extract media from this URL. Please verify the link is accessible.")



class DownloadSignalBridge(QObject):
    """Bridges synchronous background worker events to Qt signals."""

    progress_updated = Signal(str, int, int, float, int, int)
    """Args: (task_id, downloaded_bytes, total_bytes, speed, eta, percent)"""

    status_changed = Signal(str, str, str)
    """Args: (task_id, new_status, error_message)"""

    task_completed = Signal(str, str)
    """Args: (task_id, output_path)"""

    def on_progress(self, task: DownloadTask) -> None:
        """Callback listener invoked by downloader background workers.

        Emits progress_updated across thread boundary.
        """
        self.progress_updated.emit(
            task.task_id,
            task.downloaded_bytes,
            task.total_bytes,
            float(task.speed_bytes_sec or 0.0),
            int(task.eta_seconds or 0),
            int(task.progress_percentage),
        )

    def on_status_change(
        self,
        task: DownloadTask,
        old_status: DownloadStatus,
        new_status: DownloadStatus,
    ) -> None:
        """Callback listener invoked on task lifecycle status transitions.

        Emits status_changed and task_completed across thread boundary.
        """
        self.status_changed.emit(
            task.task_id,
            new_status.value,
            task.error_message or "",
        )

        if new_status == DownloadStatus.COMPLETED:
            self.task_completed.emit(task.task_id, str(task.output_path))


class ThumbnailLoader(QThread):
    """Background worker thread to fetch preview thumbnails without freezing UI."""

    thumbnail_ready = Signal(str, object)  # (task_id, QImage)
    thumbnail_failed = Signal(str)

    def __init__(
        self,
        task_id: str,
        thumbnail_url: str,
        parent: Optional[QObject] = None,
    ) -> None:
        """Initialize thumbnail loader.

        Args:
            task_id: Associated download task UUID.
            thumbnail_url: Image URL to download.
            parent: Optional parent QObject.
        """
        super().__init__(parent)
        self.task_id = task_id
        self.thumbnail_url = thumbnail_url.strip()

    def run(self) -> None:
        """Fetch remote image bytes and construct QImage."""
        if not self.thumbnail_url:
            self.thumbnail_failed.emit(self.task_id)
            return

        try:
            validate_outbound_url(self.thumbnail_url)
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                resp = client.get(self.thumbnail_url)
                resp.raise_for_status()

                image = QImage()
                if image.loadFromData(resp.content):
                    self.thumbnail_ready.emit(self.task_id, image)
                else:
                    self.thumbnail_failed.emit(self.task_id)
        except Exception as exc:
            logger.debug("Thumbnail fetch failed for %s: %s", self.task_id, exc)
            self.thumbnail_failed.emit(self.task_id)
