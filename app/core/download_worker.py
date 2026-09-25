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


def resolve_ytdlp_format(format_spec: Optional[str]) -> str:
    """Resolve user-facing format label or quality string into a resilient yt-dlp format selector.

    Handles UI presets like '1080p MP4', '720p MP4', 'Audio Only MP3', as well as raw
    format IDs with sensible fallbacks to ensure downloads prioritize Apple/QuickTime-compatible
    H.264/AAC MP4 streams.
    """
    if not format_spec or not format_spec.strip():
        return "bestvideo+bestaudio/best"

    spec = format_spec.strip()
    spec_lower = spec.lower()

    # If it is already a complex yt-dlp selector expression
    if "+" in spec or "/" in spec or "[" in spec:
        return spec

    if "audio" in spec_lower or spec_lower in ("mp3", "m4a", "aac", "wav", "flac"):
        return "bestaudio/best"

    for res in ("2160", "1440", "1080", "720", "480", "360"):
        if res in spec_lower:
            return (
                f"bestvideo[height<={res}][ext=mp4][vcodec^=avc]+bestaudio[ext=m4a][acodec^=mp4a]/"
                f"bestvideo[height<={res}][ext=mp4]+bestaudio[ext=m4a]/"
                f"bestvideo[height<={res}]+bestaudio/best[height<={res}]/"
                f"bestvideo+bestaudio/best"
            )

    if spec_lower in ("best", "best quality", "best quality (auto)", "auto", "default"):
        return "bestvideo+bestaudio/best"

    return "bestvideo+bestaudio/best"

    # For any unrecognized or custom format identifier, try it first then fallback to best
    return f"{spec}/bestvideo+bestaudio/best"


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
        self._custom_client = http_client is not None
        self._client = http_client or httpx.Client(follow_redirects=True, timeout=15.0)

    def execute(self) -> Optional[Path]:
        """Execute the download operation to completion.

        Returns:
            The Path to the final downloaded file, or None if cancelled or failed.
        """
        while self.task.is_paused and not self.task.is_cancelled:
            time.sleep(0.2)

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

        # Resolve TikTok shortdrama URL to stream or canonical video URL
        if "tiktok.com" in self.task.url.lower() and "shortdrama" in self.task.url.lower():
            resolved = self._resolve_tiktok_shortdrama_url(self.task.url)
            if resolved:
                logger.info("Resolved TikTok short drama URL %s -> %s", self.task.url, resolved)
                self.task.url = resolved

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

    def _resolve_tiktok_shortdrama_url(self, url: str) -> Optional[str]:
        """Resolve a TikTok short drama URL to its canonical stream or video URL."""
        try:
            from app.extractors.tiktok_shortdrama import TikTokShortDramaExtractor
            extractor = TikTokShortDramaExtractor(enable_syndication_search=False)
            drama_id, ep_num = extractor.extract_drama_id_and_episode(url)
            if not drama_id:
                return None
            episodes = extractor.fetch_all_episodes(drama_id)
            target_ep = ep_num or 1
            for idx, item in enumerate(episodes, start=1):
                drama_video_data = item.get("dramaInfo", {}).get("DramaVideoData", {}) if isinstance(item.get("dramaInfo"), dict) else {}
                cur_ep = drama_video_data.get("EpisodeNumber") or idx
                if cur_ep == target_ep:
                    author = item.get("author", {}).get("uniqueId") or "" if isinstance(item.get("author"), dict) else ""
                    item_id = str(item.get("id") or "")
                    if item_id:
                        author_slug = f"@{author}" if author else "@tiktok"
                        return f"https://www.tiktok.com/{author_slug}/video/{item_id}"
                    video_obj = item.get("video", {}) if isinstance(item.get("video"), dict) else {}
                    play_addr = video_obj.get("playAddr") or ""
                    if play_addr and isinstance(play_addr, str) and play_addr.startswith("http"):
                        return play_addr
                    break
        except Exception as exc:
            logger.debug("Failed resolving TikTok short drama URL %s: %s", url, exc)
        return None

    def _is_direct_stream(self, url: str) -> bool:
        """Determine if URL points directly to an accessible video/audio file."""
        clean_url = url.lower()
        direct_exts = (".mp4", ".webm", ".m3u8", ".mp3", ".m4a", ".aac")
        return any(clean_url.split("?")[0].endswith(ext) for ext in direct_exts)

    def _download_direct_stream(self, temp_path: Path) -> None:
        """Stream direct media or HLS playlist to disk with cancellation support."""
        logger.debug("Streaming direct media for task %s to %s", self.task.task_id, temp_path)

        is_hls = ".m3u8" in self.task.url.lower().split("?")[0]
        if not self._custom_client or is_hls:
            try:
                from app.services.async_downloader import AsyncDownloaderService, AsyncDownloadCancelled

                last_sync_time = time.time()

                def progress_callback(downloaded: int, total: int, speed: float, eta: Optional[int]):
                    nonlocal last_sync_time
                    self.task.update_progress(
                        downloaded_bytes=downloaded,
                        total_bytes=total,
                        speed=speed,
                        eta=eta,
                    )
                    now = time.time()
                    if now - last_sync_time >= 1.0:
                        self._sync_db_progress()
                        last_sync_time = now

                downloader = AsyncDownloaderService(concurrency=6, ffmpeg_service=self.ffmpeg)
                downloader.download(
                    url=self.task.url,
                    dest_path=temp_path,
                    progress_callback=progress_callback,
                    is_cancelled_callback=lambda: self.task.is_cancelled,
                    is_paused_callback=lambda: self.task.is_paused,
                )
                self._sync_db_progress()
                return
            except AsyncDownloadCancelled:
                raise DownloadCancelledException()
            except Exception as async_err:
                if is_hls:
                    raise
                logger.debug("Async downloader failed (%s), falling back to standard stream.", async_err)

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

                    while self.task.is_paused and not self.task.is_cancelled:
                        time.sleep(0.2)

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

            while self.task.is_paused and not self.task.is_cancelled:
                time.sleep(0.2)

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

        selected_format = resolve_ytdlp_format(self.task.format_id)
        ydl_opts = {
            "outtmpl": outtmpl,
            "format": selected_format,
            "progress_hooks": [progress_hook],
            "quiet": True,
            "no_warnings": True,
            "socket_timeout": 30,
            "retries": 10,
            "fragment_retries": 10,
            "file_access_retries": 5,
            "max_filesize": config.max_download_bytes,
        }

        # Resolve cookies file via CookieService for thread-safe, non-blocking auth
        from app.services.cookie_service import CookieService

        cookie_file = CookieService.resolve_effective_cookies_file(repo=self.repo)
        if cookie_file:
            ydl_opts["cookiefile"] = cookie_file
            logger.debug("Using cookies file for yt-dlp: %s", cookie_file)
        else:
            saved_browser = ""
            try:
                from app.database.database import DatabaseManager
                from app.database.repository import SettingsRepository
                db_mgr = self.repo.db if self.repo and hasattr(self.repo, "db") else DatabaseManager()
                saved_browser = SettingsRepository(db_mgr).get("cookies_browser") or ""
            except Exception:
                pass

            cookies_browser = saved_browser or os.environ.get("MEDIAFLOW_COOKIES_BROWSER")
            if cookies_browser:
                ydl_opts["cookiesfrombrowser"] = CookieService.parse_browser_spec(cookies_browser)
                logger.debug("Using browser cookies for yt-dlp: %s", cookies_browser)

        # Check if user requested audio-only and ffmpeg is available
        is_audio = "audio" in (self.task.format_id or "").lower() or (self.task.quality or "").lower().startswith("audio")
        if is_audio and self.ffmpeg and self.ffmpeg.is_available():
            ydl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        elif not is_audio and temp_path.suffix.lower() == ".mp4":
            ydl_opts["merge_output_format"] = "mp4"

        # If custom ffmpeg path exists, provide to yt-dlp
        if self.ffmpeg and self.ffmpeg.is_available() and self.ffmpeg._ffmpeg_path:
            ydl_opts["ffmpeg_location"] = str(Path(self.ffmpeg._ffmpeg_path).parent)

        max_attempts = 3
        transient_error_keywords = (
            "403",
            "forbidden",
            "unable to download webpage",
            "timed out",
            "timeout",
            "100004",
            "tls connect error",
            "ssl",
            "429",
            "too many requests",
            "500",
            "502",
            "503",
            "504",
            "connection reset",
            "broken pipe",
        )
        for attempt in range(1, max_attempts + 1):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([self.task.url])
                break
            except Exception as exc:
                err_text = str(exc).lower()
                if attempt < max_attempts and any(k in err_text for k in transient_error_keywords):
                    logger.warning(
                        "Download hit transient network issue (%s) for task %s, retrying with backoff (attempt %d/%d)...",
                        str(exc)[:80], self.task.task_id, attempt, max_attempts,
                    )
                    time.sleep(2.0 * attempt)
                    if any(k in err_text for k in ("403", "forbidden", "cookie")):
                        refreshed = CookieService.resolve_effective_cookies_file(repo=self.repo, force_refresh=True)
                        if refreshed:
                            ydl_opts["cookiefile"] = refreshed
                            ydl_opts.pop("cookiesfrombrowser", None)
                    continue
                raise

        # yt-dlp may append its own extension; find the resulting temp file
        temp_dir = temp_path.parent
        expected_stem = temp_path.stem
        matching_files = list(temp_dir.glob(f"{expected_stem}.*"))

        if matching_files:
            actual_temp = matching_files[0]
            if actual_temp != temp_path:
                if (
                    actual_temp.suffix.lower() in (".webm", ".mkv")
                    and temp_path.suffix.lower() == ".mp4"
                    and self.ffmpeg
                    and self.ffmpeg.is_available()
                ):
                    try:
                        self.ffmpeg.remux_to_mp4(actual_temp, temp_path)
                        actual_temp.unlink(missing_ok=True)
                    except Exception as exc:
                        logger.warning("Remux to MP4 failed, falling back to original extension: %s", exc)
                        fallback_path = temp_path.with_suffix(actual_temp.suffix)
                        actual_temp.rename(fallback_path)
                        self.task.output_path = self.task.output_path.with_suffix(actual_temp.suffix)
                else:
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
        exc_str = str(exc).lower()
        if isinstance(exc, httpx.HTTPStatusError):
            error_message = f"Server returned error code {exc.response.status_code}."
        elif isinstance(exc, ValueError):
            error_message = str(exc)
        elif "sign in to confirm your age" in exc_str or "age-restricted" in exc_str:
            error_message = "Video is age-restricted on YouTube and requires sign-in authentication."
        elif "403" in exc_str and "forbidden" in exc_str and "tiktok" in (self.task.url or "").lower():
            error_message = (
                "TikTok access forbidden (403). Cookies may have failed to load or session expired. "
                "Please verify browser cookies in Settings."
            )
        elif "ip address is blocked" in exc_str or "10204" in exc_str or ("no video formats found" in exc_str and "tiktok" in (self.task.url or "").lower()):
            error_message = (
                "TikTok requires login authentication for short drama episodes. "
                "Please export cookies.txt or configure your browser in Settings."
            )
        elif "100004" in exc_str:
            error_message = (
                "TikTok reported video temporarily unavailable (status code 100004). "
                "This usually indicates temporary CDN rate-limiting from batch downloading. Retrying will succeed."
            )
        elif "timed out" in exc_str or "timeout" in exc_str:
            error_message = (
                "Download timed out due to high network traffic or concurrency. "
                "Retrying the download or lowering concurrent downloads in Settings will resolve this."
            )
        elif "no video formats found" in exc_str:
            error_message = "No downloadable video formats found. This video may require authentication cookies."


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
