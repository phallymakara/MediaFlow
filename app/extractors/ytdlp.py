"""yt-dlp powered extractor for supported platforms and generic streams."""

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import yt_dlp

from app.core.media import MediaEpisode, MediaFormat, MediaInfo
from app.extractors.base import BaseExtractor, ExtractionError
from app.services.metadata import MetadataService

logger = logging.getLogger(__name__)

SUPPORTED_DOMAINS = [
    "youtube.com", "youtu.be",
    "tiktok.com",
    "instagram.com",
    "facebook.com", "fb.watch",
    "twitter.com", "x.com",
    "reddit.com", "v.redd.it",
    "vimeo.com",
    "twitch.tv",
]

DIRECT_EXTENSIONS = (
    ".mp4", ".mkv", ".webm", ".m4v", ".mov",
    ".mp3", ".m4a", ".aac", ".wav", ".m3u8",
)


class YtDlpExtractor(BaseExtractor):
    """Extractor leveraging yt-dlp to inspect and retrieve media metadata."""

    @property
    def platform_name(self) -> str:
        """Return the default platform identifier."""
        return "Generic Video"

    def can_handle(self, url: str) -> bool:
        """Evaluate if yt-dlp can process the given URL."""
        if not url or not url.strip():
            return False

        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False

        netloc = parsed.netloc.lower()
        if any(domain in netloc for domain in SUPPORTED_DOMAINS):
            return True

        # Check for direct media URL extensions
        path = parsed.path.lower()
        if any(path.endswith(ext) for ext in DIRECT_EXTENSIONS):
            return True

        # Allow fallback for any valid HTTP URL as yt-dlp supports over 1000+ sites
        return True

    def _resolve_platform_name(self, info: Dict[str, Any], url: str) -> str:
        """Map extractor key or URL to a clean platform name."""
        extractor = str(info.get("extractor_key") or info.get("extractor") or "").lower()
        netloc = urlparse(url).netloc.lower()

        if "youtube" in extractor or "youtube" in netloc or "youtu.be" in netloc:
            return "YouTube"
        elif "tiktok" in extractor or "tiktok" in netloc:
            return "TikTok"
        elif "instagram" in extractor or "instagram" in netloc:
            return "Instagram"
        elif "facebook" in extractor or "facebook" in netloc or "fb.watch" in netloc:
            return "Facebook"
        elif "twitter" in extractor or "x" in netloc or "twitter" in netloc:
            return "X (Twitter)"
        elif "reddit" in extractor or "reddit" in netloc:
            return "Reddit"
        elif "vimeo" in extractor or "vimeo" in netloc:
            return "Vimeo"
        elif "twitch" in extractor or "twitch" in netloc:
            return "Twitch"

        return info.get("extractor_key") or "Direct Media"

    def extract(self, url: str) -> MediaInfo:
        """Extract media metadata and normalized stream formats using yt-dlp.

        Args:
            url: The media URL to inspect.

        Returns:
            Normalized MediaInfo object.

        Raises:
            ExtractionError: If metadata extraction fails.
        """
        if not self.can_handle(url):
            raise ExtractionError("Invalid or unsupported URL format.")

        ydl_opts: Dict[str, Any] = {
            "skip_download": True,
            "extract_flat": "in_playlist",
            "socket_timeout": 15,
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": False,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            err_str = str(exc).lower()
            logger.warning("yt-dlp extraction failed for %s: %s", url, exc)
            if "private video" in err_str:
                raise ExtractionError("This video is private.") from exc
            elif "unavailable" in err_str or "not found" in err_str:
                raise ExtractionError("This video is unavailable or has been removed.") from exc
            elif "sign in" in err_str:
                raise ExtractionError("Media requires authentication or is restricted.") from exc
            raise ExtractionError("Failed to extract media information from this URL.") from exc
        except Exception as exc:
            logger.error("Unexpected error during extraction: %s", exc)
            raise ExtractionError("An error occurred while inspecting the media URL.") from exc

        if not info:
            raise ExtractionError("No media information could be retrieved.")

        # Determine if response is a playlist / series
        is_playlist = info.get("_type") == "playlist" or "entries" in info
        episodes: List[MediaEpisode] = []

        if is_playlist and info.get("entries"):
            entries = [e for e in info.get("entries") if e]
            for idx, entry in enumerate(entries, start=1):
                episodes.append(
                    MediaEpisode(
                        episode_number=idx,
                        title=MetadataService.clean_title(entry.get("title") or f"Episode {idx}"),
                        url=entry.get("url") or entry.get("webpage_url") or url,
                        duration_seconds=int(entry.get("duration") or 0) or None,
                    )
                )

        title = MetadataService.clean_title(info.get("title") or "Untitled Media")
        duration = int(info.get("duration") or 0) if info.get("duration") else None
        platform = self._resolve_platform_name(info, url)
        thumbnail = info.get("thumbnail")
        formats = self._normalize_formats(info.get("formats", []))

        return MediaInfo(
            url=url,
            title=title,
            platform=platform,
            thumbnail_url=thumbnail,
            duration_seconds=duration,
            formats=formats,
            episodes=episodes,
            is_playlist=is_playlist,
        )

    def _normalize_formats(self, raw_formats: List[Dict[str, Any]]) -> List[MediaFormat]:
        """Normalize raw yt-dlp format dictionaries into clean, deduplicated choices."""
        if not raw_formats:
            # Fallback format for direct stream
            return [
                MediaFormat(
                    format_id="best",
                    resolution="Best Quality",
                    extension="mp4",
                    note="Direct or default stream",
                    has_video=True,
                    has_audio=True,
                )
            ]

        resolutions_seen: set = set()
        normalized: List[MediaFormat] = []
        best_audio: Optional[MediaFormat] = None

        # Sort formats by height descending and tbr (total bitrate) descending
        sorted_formats = sorted(
            raw_formats,
            key=lambda f: (f.get("height") or 0, f.get("tbr") or 0, f.get("filesize") or 0),
            reverse=True,
        )

        for fmt in sorted_formats:
            vcodec = fmt.get("vcodec")
            acodec = fmt.get("acodec")
            height = fmt.get("height")
            fmt_id = str(fmt.get("format_id", ""))
            ext = str(fmt.get("ext", "mp4"))
            size = fmt.get("filesize") or fmt.get("filesize_approx")

            has_video = vcodec not in (None, "none")
            has_audio = acodec not in (None, "none")

            # Collect best audio stream
            if not has_video and has_audio:
                if best_audio is None:
                    abr = fmt.get("abr")
                    note = f"{int(abr)} kbps" if abr else "High Quality"
                    best_audio = MediaFormat(
                        format_id="bestaudio",
                        resolution="Audio Only",
                        extension="mp3",
                        filesize_approx=size,
                        note=note,
                        has_video=False,
                        has_audio=True,
                    )
                continue

            # Collect video formats grouped by standard resolution
            if has_video and height:
                res_label = f"{height}p"
                if res_label not in resolutions_seen:
                    resolutions_seen.add(res_label)
                    fps = fmt.get("fps")
                    note_parts = [res_label]
                    if fps and fps > 30:
                        note_parts.append(f"{int(fps)}fps")
                    if not has_audio:
                        note_parts.append("auto-muxed audio")

                    normalized.append(
                        MediaFormat(
                            format_id=fmt_id,
                            resolution=res_label,
                            extension=ext if ext in ("mp4", "mkv", "webm") else "mp4",
                            filesize_approx=size,
                            note=" ".join(note_parts),
                            has_video=True,
                            has_audio=has_audio,
                        )
                    )

        # Include best quality fallback at the top
        best_choice = MediaFormat(
            format_id="bestvideo+bestaudio/best",
            resolution="Best Available",
            extension="mp4",
            note="Highest quality video and audio",
            has_video=True,
            has_audio=True,
        )
        normalized.insert(0, best_choice)

        # Include audio option if discovered
        if best_audio:
            normalized.append(best_audio)
        else:
            normalized.append(
                MediaFormat(
                    format_id="bestaudio/best",
                    resolution="Audio Only",
                    extension="mp3",
                    note="Extracted audio",
                    has_video=False,
                    has_audio=True,
                )
            )

        return normalized

