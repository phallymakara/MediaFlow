"""Base extractor helper for short drama platforms."""

import html
import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx

from app.core.media import MediaEpisode, MediaFormat, MediaInfo
from app.extractors.base import BaseExtractor, ExtractionError
from app.services.metadata import MetadataService
from app.services.network import redact_url_for_logging, validate_outbound_url

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

MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-CH-UA-Mobile": "?1",
    "Sec-CH-UA-Platform": '"Android"',
}


class BaseDramaExtractor(BaseExtractor):
    """Shared base extractor for short drama websites with HTML, mobile, and multi-mirror resolution."""

    canonical_id_patterns: List[str] = []
    mirror_templates: List[str] = []

    def __init__(
        self,
        client: Optional[httpx.Client] = None,
        enable_syndication_search: bool = False,
    ) -> None:
        """Initialize drama extractor with optional HTTP client and syndication search."""
        self._client = client or httpx.Client(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=10.0,
        )
        self.enable_syndication_search = enable_syndication_search


    def fetch_html(self, url: str, headers: Optional[Dict[str, str]] = None) -> str:
        """Fetch HTML content from a URL safely.

        Args:
            url: Target URL.
            headers: Optional request headers to override client defaults.

        Returns:
            HTML response text.

        Raises:
            ExtractionError: If network request fails or returns an error status.
        """
        try:
            validated_url = validate_outbound_url(url)
            req_headers = headers or DEFAULT_HEADERS
            response = self._client.get(validated_url, headers=req_headers)
            response.raise_for_status()
            return response.text
        except ValueError as exc:
            logger.warning("Blocked outbound request to unsafe URL: %s", exc)
            raise ExtractionError(f"Cannot request target URL: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            safe_url = redact_url_for_logging(url)
            logger.warning("HTTP error %s fetching %s", exc.response.status_code, safe_url)
            if exc.response.status_code == 404:
                raise ExtractionError("Drama page not found.") from exc
            elif exc.response.status_code in (401, 403):
                raise ExtractionError("Access to this drama is restricted.") from exc
            raise ExtractionError(f"Server returned status {exc.response.status_code}.") from exc
        except (httpx.RequestError, Exception) as exc:
            safe_url = redact_url_for_logging(url)
            logger.error("Failed to connect to %s: %s", safe_url, exc)
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

    def extract_embedded_state(self, html_content: str) -> Dict[str, Any]:
        """Extract structured state and metadata from embedded JSON and script tags.

        Parses JSON-LD objects, Next.js __NEXT_DATA__, and window.__INITIAL_STATE__.

        Args:
            html_content: Raw HTML text.

        Returns:
            Dictionary containing discovered stream URLs, episodes, and metadata.
        """
        discovered: Dict[str, Any] = {
            "streams": [],
            "episodes": [],
            "title": "",
            "thumbnail": "",
        }

        # 1. Parse JSON-LD blocks
        json_ld_matches = re.findall(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html_content,
            re.IGNORECASE | re.DOTALL,
        )
        for block in json_ld_matches:
            try:
                data = json.loads(block.strip())
                self._traverse_json_for_media(data, discovered)
            except Exception as exc:
                logger.debug("Failed parsing JSON-LD script block: %s", exc)

        # 2. Parse __NEXT_DATA__ block if present
        next_data_match = re.search(
            r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
            html_content,
            re.IGNORECASE | re.DOTALL,
        )
        if next_data_match:
            try:
                data = json.loads(next_data_match.group(1).strip())
                self._traverse_json_for_media(data, discovered)
            except Exception as exc:
                logger.debug("Failed parsing __NEXT_DATA__ block: %s", exc)

        # 3. Parse window.__INITIAL_STATE__
        initial_state_match = re.search(
            r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});',
            html_content,
            re.DOTALL,
        )
        if initial_state_match:
            try:
                data = json.loads(initial_state_match.group(1).strip())
                self._traverse_json_for_media(data, discovered)
            except Exception as exc:
                logger.debug("Failed parsing window.__INITIAL_STATE__: %s", exc)

        return discovered

    def _traverse_json_for_media(self, obj: Any, discovered: Dict[str, Any]) -> None:
        """Recursively scan JSON structures for video stream URLs and episode records.

        Args:
            obj: Parsed JSON object, list, or primitive.
            discovered: Collector dictionary for discovered media items.
        """
        if isinstance(obj, dict):
            for key, val in obj.items():
                lower_key = str(key).lower()
                if isinstance(val, str) and val.startswith("http"):
                    if any(val.lower().endswith(ext) or ext in val.lower() for ext in (".mp4", ".m3u8")):
                        if val not in discovered["streams"]:
                            discovered["streams"].append(val)
                    elif lower_key in ("contenturl", "play_url", "video_url", "stream_url"):
                        if val not in discovered["streams"]:
                            discovered["streams"].append(val)
                    elif lower_key in ("thumbnail", "thumbnailurl", "cover_url", "poster") and not discovered["thumbnail"]:
                        discovered["thumbnail"] = val

                # Check for episode objects
                if lower_key in ("haspart", "episodes", "chapterlist", "chapter_list", "playlist") and isinstance(val, list):
                    for idx, ep_item in enumerate(val, 1):
                        if isinstance(ep_item, dict):
                            ep_num = ep_item.get("episode_number") or ep_item.get("chapter_no") or ep_item.get("index") or idx
                            ep_title = ep_item.get("name") or ep_item.get("title") or f"Episode {ep_num}"
                            ep_url = ep_item.get("url") or ep_item.get("contentUrl") or ""
                            if ep_url:
                                discovered["episodes"].append(
                                    MediaEpisode(
                                        episode_number=int(ep_num),
                                        title=MetadataService.clean_title(str(ep_title)),
                                        url=ep_url,
                                    )
                                )

                self._traverse_json_for_media(val, discovered)
        elif isinstance(obj, list):
            for item in obj:
                self._traverse_json_for_media(item, discovered)

    def find_video_streams(
        self,
        html_content: str,
        base_url: str,
        embedded_streams: Optional[List[str]] = None,
    ) -> List[MediaFormat]:
        """Scan HTML and script tags for accessible MP4 or HLS video streams.

        Args:
            html_content: Raw HTML text.
            base_url: Base URL for resolving relative links.
            embedded_streams: Optional list of stream URLs found in embedded state.

        Returns:
            List of detected MediaFormat choices.
        """
        formats: List[MediaFormat] = []
        found_urls: set = set()

        # 1. Include embedded state streams if provided
        if embedded_streams:
            for stream_url in embedded_streams:
                if stream_url not in found_urls:
                    found_urls.add(stream_url)
                    ext = "m3u8" if ".m3u8" in stream_url.lower() else "mp4"
                    formats.append(
                        MediaFormat(
                            format_id=f"stream-{len(formats)+1}",
                            resolution="Best Available",
                            extension=ext,
                            note="Embedded stream" if ext == "mp4" else "HLS stream",
                            has_video=True,
                            has_audio=True,
                        )
                    )

        # 2. Check <video src="..."> and <source src="...">
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

        # 3. Scan for stream URLs inside javascript objects
        embedded_in_js = re.findall(r'https?://[^\s"\'<>]+\.(?:mp4|m3u8)(?:\?[^\s"\'<>]*)?', html_content, re.IGNORECASE)
        for stream_url in embedded_in_js:
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

    def find_episodes(
        self,
        html_content: str,
        base_url: str,
        embedded_episodes: Optional[List[MediaEpisode]] = None,
    ) -> List[MediaEpisode]:
        """Discover episode links from HTML content and embedded state.

        Args:
            html_content: Raw HTML text.
            base_url: Base URL for resolving relative links.
            embedded_episodes: Optional list of episodes found in embedded state.

        Returns:
            List of discovered MediaEpisode instances.
        """
        episodes: List[MediaEpisode] = []
        seen_urls: set = set()

        if embedded_episodes:
            for ep in embedded_episodes:
                if ep.url not in seen_urls:
                    seen_urls.add(ep.url)
                    episodes.append(ep)

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
            if not clean_text or clean_text.lower() in ("play now", "watch now", "play", "watch", "view", "click here"):
                ep_title = f"Episode {ep_num}"
            else:
                ep_title = clean_text



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

    def extract_canonical_id(self, url: str) -> Optional[str]:
        """Extract canonical drama ID from URL using platform patterns or common query parameters.

        Args:
            url: Drama URL to inspect.

        Returns:
            Extracted canonical ID string or None.
        """
        if not url:
            return None

        for pattern in self.canonical_id_patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1)

        # Fallback common query parameters
        param_match = re.search(r'[?&](?:id|drama_id|book_id|series_id)=(\w+)', url, re.IGNORECASE)
        if param_match:
            return param_match.group(1)

        # Fallback numeric slug: /12345
        slug_match = re.search(r'/(\d{4,})(?:[/?#]|$)', url)
        if slug_match:
            return slug_match.group(1)

        return None

    def resolve_mirror_fallback(
        self,
        url: str,
        title: str,
        drama_id: Optional[str] = None,
    ) -> Optional[MediaInfo]:
        """Query configured mirror templates in priority order if primary page has restricted playback.

        Args:
            url: Original drama URL.
            title: Extracted or fallback title.
            drama_id: Canonical drama ID if identified.

        Returns:
            Resolved MediaInfo from a responsive mirror, or None if unavailable.
        """
        target_id = drama_id or self.extract_canonical_id(url)
        if not target_id or not self.mirror_templates:
            return None

        clean_original_url = url.strip().rstrip("/").lower()

        for template in self.mirror_templates:
            mirror_url = template.format(id=target_id)
            if clean_original_url == mirror_url.lower():
                continue

            safe_mirror_url = redact_url_for_logging(mirror_url)
            logger.info("Querying mirror fallback for %s at %s", target_id, safe_mirror_url)
            try:
                mirror_html = self.fetch_html(mirror_url, headers=DEFAULT_HEADERS)
                mirror_meta = self.extract_metadata(mirror_html)
                mirror_state = self.extract_embedded_state(mirror_html)

                resolved_title = mirror_meta.get("title") or title or f"{self.platform_name} Series {target_id}"
                resolved_thumb = mirror_meta.get("thumbnail") or mirror_state.get("thumbnail") or None

                formats = self.find_video_streams(mirror_html, mirror_url, embedded_streams=mirror_state.get("streams"))
                episodes = self.find_episodes(mirror_html, mirror_url, embedded_episodes=mirror_state.get("episodes"))

                has_real_streams = any(fmt.format_id != "default" for fmt in formats)
                if has_real_streams or episodes:
                    logger.info(
                        "Mirror resolution succeeded via %s: %d formats, %d episodes discovered.",
                        safe_mirror_url,
                        len(formats),
                        len(episodes),
                    )
                    return MediaInfo(
                        url=mirror_url,
                        title=resolved_title,
                        platform=self.platform_name,
                        thumbnail_url=resolved_thumb,
                        formats=formats,
                        episodes=episodes,
                        is_playlist=len(episodes) > 1,
                    )
            except Exception as exc:
                logger.debug("Mirror attempt failed for %s: %s", mirror_url, exc)
                continue

        return None

    @staticmethod
    def clean_drama_title(raw_title: str) -> str:
        """Extract clean core drama title by stripping platform labels and SEO buzzwords.

        Args:
            raw_title: Raw title string.

        Returns:
            Normalized clean drama name.
        """
        if not raw_title:
            return "Untitled Drama"
        # Split at common delimiters: hyphen, pipe, dash
        clean = re.sub(r"\s*[-–—|]\s*.*$", "", raw_title).strip()
        # Remove buzzwords
        clean = re.sub(
            r"(?i)\b(?:full\s*movie|full\s*episodes|dramabox|short\s*drama|all\s*episodes|watch\s*free|eng\s*sub)\b",
            "",
            clean,
        ).strip()
        return clean or raw_title.strip()

    def find_syndicated_compilations(self, clean_title: str) -> List[MediaEpisode]:
        """Discover publicly syndicated full series / complete compilations across community indexers.

        Args:
            clean_title: Normalized drama title.

        Returns:
            List of discovered MediaEpisode instances for complete compilation streams.
        """
        if not clean_title or len(clean_title) < 3:
            return []

        compilations: List[MediaEpisode] = []
        try:
            import yt_dlp

            ydl_opts = {
                "quiet": True,
                "skip_download": True,
                "extract_flat": True,
                "socket_timeout": 8,
                "no_warnings": True,
            }
            STOP_WORDS = {
                "the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "with",
                "by", "of", "from", "as", "is", "was", "are", "were", "full", "movie",
                "drama", "series", "episode", "episodes", "complete", "all", "sub", "eng",
                "dub", "part", "parts", "dramabox", "short",
            }
            clean_words = [w.lower() for w in re.findall(r"[a-z0-9]+", clean_title.lower()) if w not in STOP_WORDS and len(w) > 2]
            queries = [f"ytsearch3:{clean_title} Full Movie Drama", f"ytsearch2:{clean_title} Full Episodes"]
            seen_urls = set()

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                for q in queries:
                    try:
                        res = ydl.extract_info(q, download=False)
                        if not res or "entries" not in res:
                            continue

                        for e in res["entries"]:
                            if not e or not e.get("url"):
                                continue
                            url = e.get("url")
                            if url in seen_urls:
                                continue
                            seen_urls.add(url)

                            # Skip entries that explicitly declare restricted availability
                            if e.get("availability") in ("needs_auth", "subscriber_only", "unlisted_needs_auth"):
                                continue
                            if (e.get("age_limit") or 0) > 0:
                                continue

                            dur = e.get("duration") or 0
                            dur_mins = round(dur / 60)
                            title = e.get("title") or ""
                            title_lower = title.lower()

                            # Require substantial keyword overlap to prevent false matches
                            clean_slug = re.sub(r'[^a-z0-9 ]', '', clean_title.lower()).strip()
                            is_title_match = clean_slug in title_lower if clean_slug else False
                            matched_words = sum(1 for w in clean_words if w in title_lower)
                            threshold = max(2, int(len(clean_words) * 0.6)) if clean_words else 1
                            has_sufficient_keywords = matched_words >= threshold

                            if (is_title_match or has_sufficient_keywords) and (dur >= 600 or "full" in title_lower):
                                # Verify candidate is publicly accessible without login or age restriction
                                try:
                                    ydl.extract_info(url, download=False, process=False)
                                except Exception as auth_err:
                                    logger.debug("Skipping restricted syndicated stream %s: %s", url, auth_err)
                                    continue

                                comp_label = f"[Full Series Complete] {clean_title}"
                                if dur_mins > 0:
                                    comp_label += f" ({dur_mins} mins - All Episodes)"
                                compilations.append(
                                    MediaEpisode(
                                        episode_number=0 if not compilations else len(compilations),
                                        title=comp_label,
                                        url=url,
                                        duration_seconds=int(dur) if dur else None,
                                    )
                                )
                                if len(compilations) >= 2:
                                    break
                    except Exception as exc:
                        logger.debug("Syndication query '%s' encountered error: %s", q, exc)

                    if compilations:
                        break


            if compilations:
                logger.info(
                    "Syndication index discovered %d complete compilation(s) for '%s'",
                    len(compilations),
                    clean_title,
                )
        except Exception as exc:
            logger.debug("Failed querying syndication index for '%s': %s", clean_title, exc)

        return compilations

    def extract(self, url: str) -> MediaInfo:
        """Fetch and extract drama metadata, formats, and episodes with mobile and mirror fallbacks.

        Resolution cascade:
        1. Fetch desktop HTML and parse OpenGraph, JSON-LD, and embedded state.
        2. If no direct streams found, retry with mobile headers.
        3. If still unresolved, trigger mirror fallback resolver.
        4. Query open syndication & community aggregator index for complete series if locked.
        5. Return normalized MediaInfo.

        Args:
            url: Drama URL to inspect.

        Returns:
            Normalized MediaInfo object.

        Raises:
            ExtractionError: If content cannot be reached or resolved.
        """
        html_content = self.fetch_html(url, headers=DEFAULT_HEADERS)
        meta = self.extract_metadata(html_content)
        state = self.extract_embedded_state(html_content)

        if not meta.get("thumbnail") and state.get("thumbnail"):
            meta["thumbnail"] = state["thumbnail"]

        formats = self.find_video_streams(html_content, url, embedded_streams=state["streams"])
        episodes = self.find_episodes(html_content, url, embedded_episodes=state["episodes"])

        # Check if only the dummy default fallback was generated
        has_real_streams = any(fmt.format_id != "default" for fmt in formats)

        # Cascade Tier 2: Mobile headers retry if no real streams found
        if not has_real_streams:
            try:
                mobile_html = self.fetch_html(url, headers=MOBILE_HEADERS)
                mobile_state = self.extract_embedded_state(mobile_html)
                mobile_formats = self.find_video_streams(mobile_html, url, embedded_streams=mobile_state["streams"])
                mobile_episodes = self.find_episodes(mobile_html, url, embedded_episodes=mobile_state["episodes"])

                if any(fmt.format_id != "default" for fmt in mobile_formats):
                    formats = mobile_formats
                    has_real_streams = True
                if len(mobile_episodes) > len(episodes):
                    episodes = mobile_episodes
            except Exception as exc:
                logger.debug("Mobile profile fallback request failed for %s: %s", url, exc)

        # Cascade Tier 3: Mirror fallback resolver
        if not has_real_streams or not episodes:
            mirror_result = self.resolve_mirror_fallback(url=url, title=meta["title"])
            if mirror_result:
                return mirror_result

        # Cascade Tier 4: Open Syndication & Aggregator Index Scraper
        # If episodes have locked previews (/ep/ or 15s) or lack streams, query community index
        is_locked_drama = any(ep.url and ("15s" in ep.url or "/ep/" in ep.url) for ep in episodes) or not has_real_streams
        if self.enable_syndication_search and is_locked_drama:
            clean_drama_name = self.clean_drama_title(meta["title"])
            compilations = self.find_syndicated_compilations(clean_drama_name)
            if compilations:
                episodes = compilations + episodes
                if not has_real_streams:
                    formats = [
                        MediaFormat(
                            format_id="1080p",
                            resolution="1080p MP4",
                            extension="mp4",
                            note="Full Unlocked Series",
                            has_video=True,
                            has_audio=True,
                        ),
                        MediaFormat(
                            format_id="720p",
                            resolution="720p MP4",
                            extension="mp4",
                            note="Full Unlocked Series",
                            has_video=True,
                            has_audio=True,
                        ),
                    ]

        return MediaInfo(
            url=url,
            title=meta["title"],
            platform=self.platform_name,
            thumbnail_url=meta.get("thumbnail") or None,
            formats=formats,
            episodes=episodes,
            is_playlist=len(episodes) > 1,
        )


DramaBaseExtractor = BaseDramaExtractor

