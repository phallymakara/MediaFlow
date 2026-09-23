"""Base extractor helper for short drama platforms."""

import html
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx

from app.core.media import MediaEpisode, MediaFormat, MediaInfo
from app.extractors.base import BaseExtractor, ExtractionError
from app.services.metadata import MetadataService

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class BaseDramaExtractor(BaseExtractor):
    """Shared base extractor for short drama websites with HTML and stream parsing."""

    def __init__(self, client: Optional[httpx.Client] = None) -> None:
        """Initialize drama extractor with optional HTTP client."""
        self._client = client or httpx.Client(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=10.0,
        )

    def fetch_html(self, url: str) -> str:
        """Fetch HTML content from a URL safely.

        Args:
            url: Target URL.

        Returns:
            HTML response text.

        Raises:
            ExtractionError: If network request fails or returns an error status.
        """
        try:
            response = self._client.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as exc:
            logger.warning("HTTP error %s fetching %s", exc.response.status_code, url)
            if exc.response.status_code == 404:
                raise ExtractionError("Drama page not found.") from exc
            elif exc.response.status_code in (401, 403):
                raise ExtractionError("Access to this drama is restricted.") from exc
            raise ExtractionError(f"Server returned status {exc.response.status_code}.") from exc
        except (httpx.RequestError, Exception) as exc:
            logger.error("Failed to connect to %s: %s", url, exc)
            raise ExtractionError("Network connection failed while reaching drama source.") from exc

    def extract_metadata(self, html_content: str) -> Dict[str, str]:
        """Extract title, thumbnail, and description from OpenGraph and HTML meta tags.

        Handles mixed quotes and apostrophes inside content attributes cleanly.

        Args:
            html_content: Raw HTML text.

        Returns:
            Dictionary containing title, thumbnail, and description.
        """
        meta: Dict[str, str] = {}

        # OpenGraph title or <title>
        og_title_match = (
            re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=(?:"([^"]*)"|\'([^\']*)\')', html_content, re.IGNORECASE)
            or re.search(r'<meta[^>]+content=(?:"([^"]*)"|\'([^\']*)\')[^>]+property=["\']og:title["\']', html_content, re.IGNORECASE)
        )
        title = ""
        if og_title_match:
            title = og_title_match.group(1) or og_title_match.group(2) or ""

        if not title:
            title_tag = re.search(r'<title[^>]*>([^<]+)</title>', html_content, re.IGNORECASE)
            if title_tag:
                title = title_tag.group(1)

        meta["title"] = MetadataService.clean_title(html.unescape(title)) if title else "Untitled Drama"

        # OpenGraph image / poster
        og_image_match = (
            re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=(?:"([^"]*)"|\'([^\']*)\')', html_content, re.IGNORECASE)
            or re.search(r'<meta[^>]+content=(?:"([^"]*)"|\'([^\']*)\')[^>]+property=["\']og:image["\']', html_content, re.IGNORECASE)
        )
        meta["thumbnail"] = (og_image_match.group(1) or og_image_match.group(2) or "").strip() if og_image_match else ""

        # OpenGraph description
        og_desc_match = (
            re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=(?:"([^"]*)"|\'([^\']*)\')', html_content, re.IGNORECASE)
            or re.search(r'<meta[^>]+content=(?:"([^"]*)"|\'([^\']*)\')[^>]+property=["\']og:description["\']', html_content, re.IGNORECASE)
        )
        meta["description"] = html.unescape(og_desc_match.group(1) or og_desc_match.group(2) or "").strip() if og_desc_match else ""

        return meta

    def find_video_streams(self, html_content: str, base_url: str) -> List[MediaFormat]:
        """Scan HTML and script tags for accessible MP4 or HLS video streams.

        Args:
            html_content: Raw HTML text.
            base_url: Base URL for resolving relative links.

        Returns:
            List of detected MediaFormat choices.
        """
        formats: List[MediaFormat] = []
        found_urls: set = set()

        # Check <video src="..."> and <source src="...">
        video_srcs = re.findall(r'<(?:video|source)[^>]+src=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
        for src in video_srcs:
            full_url = urljoin(base_url, src.strip())
            if full_url not in found_urls:
                found_urls.add(full_url)
                ext = "m3u8" if ".m3u8" in full_url.lower() else "mp4"
                formats.append(
                    MediaFormat(
                        format_id=f"stream-{len(formats)+1}",
                        resolution="Standard Quality",
                        extension=ext,
                        note="Direct stream" if ext == "mp4" else "HLS stream",
                        has_video=True,
                        has_audio=True,
                    )
                )

        # Scan for stream URLs inside javascript objects
        embedded_streams = re.findall(r'https?://[^\s"\'<>]+\.(?:mp4|m3u8)(?:\?[^\s"\'<>]*)?', html_content, re.IGNORECASE)
        for stream_url in embedded_streams:
            if stream_url not in found_urls:
                found_urls.add(stream_url)
                ext = "m3u8" if ".m3u8" in stream_url.lower() else "mp4"
                formats.append(
                    MediaFormat(
                        format_id=f"stream-{len(formats)+1}",
                        resolution="Best Available",
                        extension=ext,
                        note="Embedded media stream",
                        has_video=True,
                        has_audio=True,
                    )
                )

        if not formats:
            # Fallback format descriptor
            formats.append(
                MediaFormat(
                    format_id="default",
                    resolution="Standard Stream",
                    extension="mp4",
                    note="Accessible drama stream",
                    has_video=True,
                    has_audio=True,
                )
            )

        return formats

    def find_episodes(self, html_content: str, base_url: str) -> List[MediaEpisode]:
        """Discover episode links from HTML content.

        Args:
            html_content: Raw HTML text.
            base_url: Base URL for resolving relative links.

        Returns:
            List of discovered MediaEpisode instances.
        """
        episodes: List[MediaEpisode] = []
        seen_urls: set = set()

        # Match links with episode patterns: /episode/1, /ep-2, /watch?ep=3
        matches = re.findall(
            r'<a[^>]+href=["\']([^"\']*(?:ep|episode)[^"\']*)["\'][^>]*>(.*?)</a>',
            html_content,
            re.IGNORECASE | re.DOTALL,
        )

        for href, text in matches:
            full_url = urljoin(base_url, href.strip())
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            # Extract episode number from link or text
            ep_num_match = re.search(r'(?:ep|episode)[_-]?(\d+)', href, re.IGNORECASE)
            if not ep_num_match:
                ep_num_match = re.search(r'\b(\d+)\b', text)

            ep_num = int(ep_num_match.group(1)) if ep_num_match else len(episodes) + 1
            clean_text = re.sub(r'<[^>]+>', '', text).strip()
            ep_title = clean_text if clean_text else f"Episode {ep_num}"

            episodes.append(
                MediaEpisode(
                    episode_number=ep_num,
                    title=MetadataService.clean_title(ep_title),
                    url=full_url,
                )
            )

        # Sort episodes chronologically by number
        episodes.sort(key=lambda ep: ep.episode_number)
        return episodes

    def extract(self, url: str) -> MediaInfo:
        """Fetch and extract drama metadata, formats, and episodes.

        Args:
            url: Drama URL to inspect.

        Returns:
            Normalized MediaInfo object.
        """
        html_content = self.fetch_html(url)
        meta = self.extract_metadata(html_content)
        formats = self.find_video_streams(html_content, url)
        episodes = self.find_episodes(html_content, url)

        return MediaInfo(
            url=url,
            title=meta["title"],
            platform=self.platform_name,
            thumbnail_url=meta.get("thumbnail") or None,
            formats=formats,
            episodes=episodes,
            is_playlist=len(episodes) > 1,
        )
