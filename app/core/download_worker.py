"""Download worker handling background media transfer and stream assembly."""

import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx
import yt_dlp

from app.config import get_config
from app.core.tasks import DownloadTask
from app.database.models import DownloadStatus
from app.database.repository import DownloadRepository
from app.services.ffmpeg import FFmpegService
from app.services.network import redact_url_for_logging, validate_outbound_url
from app.services.storage import StorageService

logger = logging.getLogger(__name__)

CHUNK_SIZE = 64 * 1024  # 64 KB per read chunk


class DownloadCancelledException(Exception):
    """Internal exception raised to terminate worker when cancellation is triggered."""

    pass


class DownloadWorker:
    """Executes a single media download in a worker thread."""

    def __init__(
        self,
        task: DownloadTask,
        storage_service: StorageService,
        ffmpeg_service: Optional[FFmpegService] = None,
        repository: Optional[DownloadRepository] = None,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        """Initialize download worker.

        Args:
            task: The DownloadTask to execute.
            storage_service: StorageService for temp files and final commits.
            ffmpeg_service: Optional FFmpegService for stream processing.
            repository: Optional DownloadRepository for database synchronization.
            http_client: Optional HTTP client for direct streaming.
        """
        self.task = task
        self.storage = storage_service
        self.ffmpeg = ffmpeg_service
        self.repo = repository
        self._client = http_client or httpx.Client(follow_redirects=True, timeout=15.0)

    def execute(self) -> Optional[Path]:
        """Execute the download operation to completion.

        Returns:
            The Path to the final downloaded file, or None if cancelled or failed.
        """
        if self.task.is_cancelled:
            self._handle_cancellation(None)
            return None

        try:
            validate_outbound_url(self.task.url)
        except Exception as exc:
            self._handle_failure(None, exc)
            return None

        self.task.set_status(DownloadStatus.DOWNLOADING)
        self._sync_db_status()

        ext = self.task.output_path.suffix or ".mp4"
        temp_path = self.storage.get_temp_path(prefix=self.task.task_id, extension=ext)

        try:
            if self._is_direct_stream(self.task.url):
                self._download_direct_stream(temp_path)
            else:
                self._download_ytdlp(temp_path)

            if self.task.is_cancelled:
                self._handle_cancellation(temp_path)
                return None

            # Transition to processing if post-processing needed
            self.task.set_status(DownloadStatus.PROCESSING)
            self._sync_db_status()

            # Atomic move from temp to final destination
            final_path = self.storage.commit_temp_file(temp_path, self.task.output_path)

            self.task.set_status(DownloadStatus.COMPLETED)
            self._sync_db_status()
            logger.info("Task %s completed successfully: %s", self.task.task_id, final_path)
            return final_path

        except DownloadCancelledException:
            self._handle_cancellation(temp_path)
            return None
        except Exception as exc:
            self._handle_failure(temp_path, exc)
            return None

    def _is_direct_stream(self, url: str) -> bool:
        """Determine if URL points directly to an accessible video/audio file."""
        clean_url = url.lower()
        direct_exts = (".mp4", ".webm", ".m3u8", ".mp3", ".m4a", ".aac")
        return any(clean_url.split("?")[0].endswith(ext) for ext in direct_exts)

    def _download_direct_stream(self, temp_path: Path) -> None:
        """Stream direct media file to disk in chunks with cancellation support."""
        logger.debug("Streaming direct media for task %s to %s", self.task.task_id, temp_path)
        config = get_config()
        max_bytes = config.max_download_bytes

        with self._client.stream("GET", self.task.url) as response:
            response.raise_for_status()

            content_type = response.headers.get("content-type", "").lower()
            disallowed_types = ("text/html", "application/json", "application/javascript", "text/javascript")
            if any(content_type.startswith(dt) for dt in disallowed_types):
                raise ValueError("Response is not a valid media stream.")

            total_bytes = 0
            content_length = response.headers.get("content-length")
            if content_length and content_length.isdigit():
                total_bytes = int(content_length)
                if total_bytes > max_bytes:
                    raise ValueError("File size exceeds maximum allowed download limit.")

            downloaded = 0
            start_time = time.time()
            last_sync_time = start_time

            with open(temp_path, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=CHUNK_SIZE):
                    if self.task.is_cancelled:
                        raise DownloadCancelledException()

                    if chunk:
                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            raise ValueError("File size exceeded maximum allowed download limit.")

                        f.write(chunk)

                        elapsed = max(0.001, time.time() - start_time)
                        speed = downloaded / elapsed
                        eta = int((total_bytes - downloaded) / speed) if total_bytes > downloaded and speed > 0 else None

                        self.task.update_progress(
                            downloaded_bytes=downloaded,
                            total_bytes=total_bytes,
                            speed=speed,
                            eta=eta,
                        )

                        # Sync progress to database once per second
                        now = time.time()
                        if now - last_sync_time >= 1.0:
                            self._sync_db_progress()
                            last_sync_time = now

            self._sync_db_progress()

    def _download_ytdlp(self, temp_path: Path) -> None:
        """Execute download using yt-dlp with live progress hook and cancellation checks."""
        logger.debug("Downloading via yt-dlp for task %s to %s", self.task.task_id, temp_path)
        config = get_config()

        # Output template matching temporary path without yt-dlp auto-extension
        outtmpl = str(temp_path.with_suffix("")) + ".%(ext)s"

        def progress_hook(d: dict) -> None:
            if self.task.is_cancelled:
                raise DownloadCancelledException()

            if d.get("status") == "downloading":
                downloaded = d.get("downloaded_bytes") or 0
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                speed = d.get("speed")
                eta = d.get("eta")

                self.task.update_progress(
                    downloaded_bytes=downloaded,
                    total_bytes=total,
                    speed=speed,
                    eta=eta,
                )

            elif d.get("status") == "error":
                raise ValueError("Download failed during stream extraction.")

        selected_format = self.task.format_id or "bestvideo+bestaudio/best"
        ydl_opts = {
            "outtmpl": outtmpl,
            "format": selected_format,
            "progress_hooks": [progress_hook],
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 15,
            "max_filesize": config.max_download_bytes,
        }

        # If custom ffmpeg path exists, provide to yt-dlp
        if self.ffmpeg and self.ffmpeg.is_available() and self.ffmpeg._ffmpeg_path:
            ydl_opts["ffmpeg_location"] = str(Path(self.ffmpeg._ffmpeg_path).parent)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([self.task.url])

        # yt-dlp may append its own extension; find the resulting temp file
        temp_dir = temp_path.parent
        expected_stem = temp_path.stem
        matching_files = list(temp_dir.glob(f"{expected_stem}.*"))

        if matching_files:
            actual_temp = matching_files[0]
            if actual_temp != temp_path:
                actual_temp.rename(temp_path)

    def _handle_cancellation(self, temp_path: Optional[Path]) -> None:
        """Clean up partial files and mark task as cancelled."""
        logger.info("Cleaning up cancelled task: %s", self.task.task_id)
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError as exc:
                logger.warning("Could not delete partial temp file: %s", exc)

        self.task.set_status(DownloadStatus.CANCELLED)
        self._sync_db_status()

    def _handle_failure(self, temp_path: Optional[Path], exc: Exception) -> None:
        """Clean up and record task failure with a safe user-facing message."""
        logger.error(
            "Download failed for task %s (url=%s): %s",
            self.task.task_id,
            redact_url_for_logging(self.task.url),
            exc,
        )
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

        error_message = "Download failed due to a network or connection issue."
        if isinstance(exc, httpx.HTTPStatusError):
            error_message = f"Server returned error code {exc.response.status_code}."
        elif isinstance(exc, ValueError):
            error_message = str(exc)

        self.task.set_status(DownloadStatus.FAILED, error_message=error_message)
        self._sync_db_status()

    def _sync_db_status(self) -> None:
        """Update task status and error in repository if available."""
        if self.repo:
            try:
                self.repo.update_status(
                    task_id=self.task.task_id,
                    status=self.task.status,
                    error_message=self.task.error_message,
                )
            except Exception as exc:
                logger.error("Database sync error for status: %s", exc)

    def _sync_db_progress(self) -> None:
        """Update byte counts in repository if available."""
        if self.repo:
            try:
                self.repo.update_progress(
                    task_id=self.task.task_id,
                    downloaded_bytes=self.task.downloaded_bytes,
                    total_bytes=self.task.total_bytes,
                )
            except Exception as exc:
                logger.debug("Database sync error for progress: %s", exc)
