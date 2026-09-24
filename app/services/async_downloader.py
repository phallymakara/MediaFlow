"""Asynchronous high-concurrency media and HLS segment downloader."""

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Callable, List, Optional
from urllib.parse import urljoin, urlparse

import aiohttp

from app.config import get_config
from app.services.ffmpeg import FFmpegService
from app.services.network import redact_url_for_logging, validate_outbound_url

logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 6
MAX_RETRIES = 3
CHUNK_BUFFER_SIZE = 128 * 1024  # 128 KB buffer


class AsyncDownloadCancelled(Exception):
    """Exception raised when an asynchronous download task is cancelled."""

    pass


class AsyncDownloaderService:
    """Manages high-concurrency downloads for direct video streams and HLS playlists."""

    def __init__(
        self,
        concurrency: int = DEFAULT_CONCURRENCY,
        ffmpeg_service: Optional[FFmpegService] = None,
    ) -> None:
        """Initialize async downloader service.

        Args:
            concurrency: Maximum number of concurrent chunk or segment connections.
            ffmpeg_service: Optional FFmpegService for stream concatenation and remuxing.
        """
        self.concurrency = max(1, min(concurrency, 16))
        self.ffmpeg = ffmpeg_service or FFmpegService()

    def download(
        self,
        url: str,
        dest_path: Path,
        progress_callback: Optional[Callable[[int, int, float, Optional[int]], None]] = None,
        is_cancelled_callback: Optional[Callable[[], bool]] = None,
        is_paused_callback: Optional[Callable[[], bool]] = None,
    ) -> Path:
        """Synchronous entry point that runs the async download loop to completion.

        Args:
            url: Validated media or playlist URL.
            dest_path: Destination path for the completed file.
            progress_callback: Callback receiving (downloaded_bytes, total_bytes, speed_bps, eta_sec).
            is_cancelled_callback: Callback returning True if task is cancelled.
            is_paused_callback: Callback returning True if task is paused.

        Returns:
            The Path to the finalized download file.

        Raises:
            AsyncDownloadCancelled: If download was cancelled by user.
            ValueError: If URL or response is invalid.
            RuntimeError: If download fails.
        """
        validate_outbound_url(url)
        return asyncio.run(
            self._download_async(
                url=url,
                dest_path=dest_path,
                progress_callback=progress_callback,
                is_cancelled_callback=is_cancelled_callback,
                is_paused_callback=is_paused_callback,
            )
        )

    async def _download_async(
        self,
        url: str,
        dest_path: Path,
        progress_callback: Optional[Callable[[int, int, float, Optional[int]], None]] = None,
        is_cancelled_callback: Optional[Callable[[], bool]] = None,
        is_paused_callback: Optional[Callable[[], bool]] = None,
    ) -> Path:
        """Core async dispatcher routing between HLS playlists and direct files."""
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=30)
        connector = aiohttp.TCPConnector(limit=self.concurrency)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
        }

        async with aiohttp.ClientSession(
            connector=connector, timeout=timeout, headers=headers
        ) as session:
            if self._is_hls_stream(url):
                return await self._download_hls(
                    session=session,
                    url=url,
                    dest_path=dest_path,
                    progress_callback=progress_callback,
                    is_cancelled_callback=is_cancelled_callback,
                    is_paused_callback=is_paused_callback,
                )
            else:
                return await self._download_direct(
                    session=session,
                    url=url,
                    dest_path=dest_path,
                    progress_callback=progress_callback,
                    is_cancelled_callback=is_cancelled_callback,
                    is_paused_callback=is_paused_callback,
                )

    @staticmethod
    def _is_hls_stream(url: str) -> bool:
        """Check if URL points to an HLS playlist."""
        clean_url = url.split("?")[0].lower()
        return clean_url.endswith(".m3u8")

    async def _download_direct(
        self,
        session: aiohttp.ClientSession,
        url: str,
        dest_path: Path,
        progress_callback: Optional[Callable[[int, int, float, Optional[int]], None]],
        is_cancelled_callback: Optional[Callable[[], bool]],
        is_paused_callback: Optional[Callable[[], bool]],
    ) -> Path:
        """Stream a direct media file asynchronously with cancellation checks."""
        config = get_config()
        max_bytes = config.max_download_bytes
        safe_url = redact_url_for_logging(url)

        async with session.get(url) as response:
            if response.status >= 400:
                raise RuntimeError(f"Server returned HTTP status {response.status}")

            total_bytes = int(response.headers.get("Content-Length", 0))
            if total_bytes > max_bytes:
                raise ValueError("File size exceeds maximum allowed download limit.")

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            downloaded = 0
            start_time = time.time()

            with open(dest_path, "wb") as f:
                async for chunk in response.content.iter_chunked(CHUNK_BUFFER_SIZE):
                    if is_cancelled_callback and is_cancelled_callback():
                        raise AsyncDownloadCancelled("Download cancelled by user.")

                    while is_paused_callback and is_paused_callback():
                        if is_cancelled_callback and is_cancelled_callback():
                            raise AsyncDownloadCancelled("Download cancelled by user.")
                        await asyncio.sleep(0.2)

                    f.write(chunk)
                    downloaded += len(chunk)

                    if downloaded > max_bytes:
                        raise ValueError("File size exceeded maximum allowed download limit.")

                    if progress_callback:
                        elapsed = max(0.001, time.time() - start_time)
                        speed = downloaded / elapsed
                        eta = (
                            int((total_bytes - downloaded) / speed)
                            if total_bytes > downloaded and speed > 0
                            else None
                        )
                        progress_callback(downloaded, total_bytes, speed, eta)

        logger.info("Direct async download complete for %s (%d bytes)", safe_url, downloaded)
        return dest_path

    async def _download_hls(
        self,
        session: aiohttp.ClientSession,
        url: str,
        dest_path: Path,
        progress_callback: Optional[Callable[[int, int, float, Optional[int]], None]],
        is_cancelled_callback: Optional[Callable[[], bool]],
        is_paused_callback: Optional[Callable[[], bool]],
    ) -> Path:
        """Download HLS segments in parallel and remux into a final MP4."""
        safe_url = redact_url_for_logging(url)
        logger.info("Parsing HLS playlist for %s", safe_url)

        segment_urls = await self._parse_hls_playlist(session, url)
        if not segment_urls:
            raise ValueError("No playable video segments found in HLS playlist.")

        total_segments = len(segment_urls)
        logger.info("Discovered %d segments for %s", total_segments, safe_url)

        temp_dir = dest_path.parent / f"_hls_tmp_{dest_path.stem}"
        temp_dir.mkdir(parents=True, exist_ok=True)

        downloaded_bytes = 0
        completed_segments = 0
        start_time = time.time()
        semaphore = asyncio.Semaphore(self.concurrency)
        segment_files: List[Optional[Path]] = [None] * total_segments

        async def fetch_segment(index: int, seg_url: str):
            nonlocal downloaded_bytes, completed_segments
            if is_cancelled_callback and is_cancelled_callback():
                return

            seg_path = temp_dir / f"seg_{index:06d}.ts"
            async with semaphore:
                for attempt in range(MAX_RETRIES):
                    if is_cancelled_callback and is_cancelled_callback():
                        return
                    try:
                        async with session.get(seg_url) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                with open(seg_path, "wb") as f:
                                    f.write(data)
                                segment_files[index] = seg_path
                                downloaded_bytes += len(data)
                                completed_segments += 1

                                if progress_callback:
                                    elapsed = max(0.001, time.time() - start_time)
                                    speed = downloaded_bytes / elapsed
                                    # Estimate total bytes based on average segment size
                                    avg_seg = downloaded_bytes / max(1, completed_segments)
                                    est_total = int(avg_seg * total_segments)
                                    eta = (
                                        int((est_total - downloaded_bytes) / speed)
                                        if est_total > downloaded_bytes and speed > 0
                                        else None
                                    )
                                    progress_callback(
                                        downloaded_bytes, est_total, speed, eta
                                    )
                                return
                    except Exception as err:
                        if attempt == MAX_RETRIES - 1:
                            logger.warning(
                                "Segment %d failed after %d retries: %s", index, MAX_RETRIES, err
                            )
                        await asyncio.sleep(0.5 * (attempt + 1))

        try:
            tasks = [fetch_segment(i, u) for i, u in enumerate(segment_urls)]
            await asyncio.gather(*tasks)

            if is_cancelled_callback and is_cancelled_callback():
                raise AsyncDownloadCancelled("Download cancelled by user.")

            valid_segments = [p for p in segment_files if p and p.exists()]
            if not valid_segments:
                raise RuntimeError("Failed to download HLS segments.")

            # Concat segments into a unified transport stream
            raw_ts_path = temp_dir / "combined.ts"
            with open(raw_ts_path, "wb") as out_f:
                for seg_path in valid_segments:
                    with open(seg_path, "rb") as in_f:
                        shutil.copyfileobj(in_f, out_f)

            # Remux to MP4 using FFmpeg if available, or move TS if remux fails
            if self.ffmpeg.is_available():
                logger.info("Remuxing combined HLS transport stream to MP4: %s", dest_path)
                try:
                    self.ffmpeg.remux(raw_ts_path, dest_path)
                except Exception as ffmpeg_err:
                    logger.warning("FFmpeg remux failed (%s), saving stream directly.", ffmpeg_err)
                    shutil.move(str(raw_ts_path), str(dest_path))
            else:
                shutil.move(str(raw_ts_path), str(dest_path))

            logger.info("HLS download completed: %s", dest_path)
            return dest_path

        finally:
            # Clean up temporary segments folder
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    async def _parse_hls_playlist(
        self, session: aiohttp.ClientSession, playlist_url: str
    ) -> List[str]:
        """Parse master or media HLS playlist and return ordered segment URLs."""
        async with session.get(playlist_url) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Failed to fetch HLS playlist: HTTP {resp.status}")
            text = await resp.text()

        lines = [line.strip() for line in text.splitlines() if line.strip()]

        # Check if master playlist
        if any(line.startswith("#EXT-X-STREAM-INF") for line in lines):
            best_variant_url = None
            max_bandwidth = -1
            current_bw = 0

            for i, line in enumerate(lines):
                if line.startswith("#EXT-X-STREAM-INF"):
                    # Extract BANDWIDTH attribute
                    import re

                    bw_match = re.search(r"BANDWIDTH=(\d+)", line)
                    if bw_match:
                        current_bw = int(bw_match.group(1))
                    else:
                        current_bw = 0
                elif not line.startswith("#") and i > 0 and lines[i - 1].startswith("#EXT-X-STREAM-INF"):
                    if current_bw > max_bandwidth:
                        max_bandwidth = current_bw
                        best_variant_url = urljoin(playlist_url, line)

            if best_variant_url:
                logger.debug("Following highest bandwidth HLS variant: %s", best_variant_url)
                return await self._parse_hls_playlist(session, best_variant_url)

        # Parse media segments
        segments = []
        for line in lines:
            if not line.startswith("#"):
                segments.append(urljoin(playlist_url, line))

        return segments
