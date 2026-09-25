"""TikTok Short Drama platform extractor supporting series and individual episodes."""

import http.cookiejar
import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

from app.core.media import MediaEpisode, MediaFormat, MediaInfo
from app.extractors.base import ExtractionError
from app.extractors.drama_base import DEFAULT_HEADERS, BaseDramaExtractor
from app.services.metadata import MetadataService
from app.services.network import redact_url_for_logging, validate_outbound_url

logger = logging.getLogger(__name__)

# Regular expression matching TikTok short drama URL variants:
# - https://www.tiktok.com/shortdrama/episode/7684287182416417813
# - https://www.tiktok.com/shortdrama/episode/7684287182416417813/1
# - https://www.tiktok.com/shortdrama/episode/en/7684287182416417813/1
# - https://www.tiktok.com/shortdrama/episode/vi/7684287182416417813/2
# - https://www.tiktok.com/shortdrama/7684287182416417813
# - https://www.tiktok.com/shortdrama/7684287182416417813/1
TIKTOK_DRAMA_PATTERN = re.compile(
    r'/shortdrama(?:/episode)?(?:/([a-zA-Z]{2,3}(?:-[a-zA-Z]{2})?))?(?:/[a-zA-Z_-]+)?/(\d+)(?:/(\d+))?',
    re.IGNORECASE,
)


class TikTokShortDramaExtractor(BaseDramaExtractor):
    """Custom extractor for TikTok Short Drama (tiktok.com/shortdrama/...) series and episodes."""

    canonical_id_patterns: List[str] = [
        r'/shortdrama(?:/episode)?(?:/[a-zA-Z_-]+)?/(\d+)',
    ]

    def __init__(
        self,
        client: Optional[httpx.Client] = None,
        enable_syndication_search: bool = False,
    ) -> None:
        """Initialize TikTok Short Drama extractor."""
        if client is None:
            jar = self._load_cookie_jar()
            client = httpx.Client(
                headers=DEFAULT_HEADERS,
                cookies=jar,
                follow_redirects=True,
                timeout=10.0,
            )
        super().__init__(client=client, enable_syndication_search=enable_syndication_search)

    @staticmethod
    def _load_cookie_jar() -> Optional[http.cookiejar.MozillaCookieJar]:
        try:
            from app.services.cookie_service import CookieService
            cf = CookieService.resolve_effective_cookies_file()
            if cf and os.path.exists(cf):
                jar = http.cookiejar.MozillaCookieJar(cf)
                jar.load(ignore_discard=True, ignore_expires=True)
                logger.debug("Loaded cookie jar for TikTok from %s", cf)
                return jar
        except Exception as exc:
            logger.warning("Failed loading cookie jar for TikTok: %s", exc)
        return None

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "TikTok Short Drama"

    def can_handle(self, url: str) -> bool:
        """Return True if URL is a TikTok Short Drama link."""
        if not url or not url.strip():
            return False
        parsed = urlparse(url.strip())
        netloc = parsed.netloc.lower()
        if "tiktok.com" not in netloc and "tiktokv.com" not in netloc:
            return False
        path = parsed.path.lower()
        return "shortdrama" in path

    def extract_drama_id_and_episode(self, url: str) -> Tuple[Optional[str], Optional[int]]:
        """Extract drama ID and optional target episode number from URL.

        Args:
            url: The TikTok short drama URL.

        Returns:
            Tuple of (drama_id, target_episode_number).
        """
        parsed = urlparse(url.strip())
        match = TIKTOK_DRAMA_PATTERN.search(parsed.path)
        if match:
            drama_id = match.group(2)
            ep_num = int(match.group(3)) if match.group(3) else None
            return drama_id, ep_num
        return None, None

    def extract_language(self, url: str) -> Optional[str]:
        """Extract language prefix from URL if present (e.g. 'en', 'vi')."""
        parsed = urlparse(url.strip())
        match = TIKTOK_DRAMA_PATTERN.search(parsed.path)
        if match and match.group(1):
            return match.group(1).lower()
        return None

    def extract_canonical_id(self, url: str) -> Optional[str]:
        """Extract canonical drama ID."""
        drama_id, _ = self.extract_drama_id_and_episode(url)
        return drama_id

    def fetch_drama_detail(self, drama_id: str, language: str = "en") -> Dict[str, Any]:
        """Fetch short drama metadata using TikTok's web drama API.

        Args:
            drama_id: Numeric drama ID string.
            language: Desired localization language (defaults to 'en').

        Returns:
            Dictionary containing series metadata from dramaInfo.
        """
        endpoint = "https://www.tiktok.com/api/drama/detail/"
        params = {
            "dramaID": drama_id,
            "aid": "1988",
            "language": language,
        }
        try:
            response = self._client.get(endpoint, params=params, headers=DEFAULT_HEADERS)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                return data.get("dramaInfo") or {}
        except Exception as exc:
            logger.warning("Failed fetching drama detail for ID %s: %s", drama_id, exc)

        return {}

    def fetch_all_episodes(
        self,
        drama_id: str,
        max_episodes: int = 300,
        language: str = "en",
    ) -> List[Dict[str, Any]]:
        """Fetch all episode items across paginated API responses.

        Args:
            drama_id: Numeric drama ID string.
            max_episodes: Maximum episodes to retrieve safely.
            language: Desired localization language (defaults to 'en').

        Returns:
            List of raw episode item dictionaries.
        """
        endpoint = "https://www.tiktok.com/api/drama/episode/item_list/"
        cursor = "0"
        has_more = True
        all_items: List[Dict[str, Any]] = []

        while has_more and len(all_items) < max_episodes:
            params = {
                "dramaID": drama_id,
                "cursor": cursor,
                "count": "30",
                "aid": "1988",
                "language": language,
            }
            try:
                response = self._client.get(endpoint, params=params, headers=DEFAULT_HEADERS)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    break

                batch = data.get("itemList") or []
                if not batch:
                    break

                all_items.extend(batch)
                has_more = bool(data.get("hasMore", False))
                cursor = str(data.get("cursor", ""))
                if not cursor or cursor == "0":
                    break
            except Exception as exc:
                logger.warning("Error fetching episode batch at cursor %s for drama %s: %s", cursor, drama_id, exc)
                break

        return all_items

    def extract(self, url: str) -> MediaInfo:
        """Extract drama metadata, episode catalog, and streaming formats.

        Args:
            url: Target TikTok short drama URL.

        Returns:
            Normalized MediaInfo object.

        Raises:
            ExtractionError: If metadata cannot be retrieved or URL is invalid.
        """
        validated_url = validate_outbound_url(url)
        safe_url = redact_url_for_logging(validated_url)

        drama_id, target_ep_num = self.extract_drama_id_and_episode(validated_url)
        if not drama_id:
            raise ExtractionError("Invalid or unsupported TikTok Short Drama URL format.")

        lang = self.extract_language(validated_url) or "en"
        logger.info("Extracting TikTok Short Drama for ID %s (target ep: %s, lang: %s)", drama_id, target_ep_num, lang)

        # 1. Fetch metadata from official web drama API
        drama_info = self.fetch_drama_detail(drama_id, language=lang)

        # 2. Extract series title, description, cover
        series_title = drama_info.get("dramaName") or ""
        description = drama_info.get("description") or ""

        cover_url = ""
        covers = drama_info.get("cover", {}).get("urlList", []) if isinstance(drama_info.get("cover"), dict) else []
        if covers and isinstance(covers, list) and isinstance(covers[0], str):
            cover_url = covers[0]
        elif isinstance(drama_info.get("zoomCover"), dict):
            zoom = drama_info.get("zoomCover", {})
            cover_url = zoom.get("720") or zoom.get("480") or zoom.get("240") or ""

        # Fallback to HTML meta tags if API returned no title
        if not series_title:
            try:
                html_content = self.fetch_html(validated_url, headers=DEFAULT_HEADERS)
                meta = self.extract_metadata(html_content)
                series_title = meta.get("title") or ""
                if not cover_url:
                    cover_url = meta.get("thumbnail") or ""
                if not description:
                    description = meta.get("description") or ""
            except Exception as exc:
                logger.debug("HTML fallback scrape failed for %s: %s", safe_url, exc)

        series_title = MetadataService.clean_title(series_title) or f"TikTok Drama {drama_id}"

        # 3. Retrieve all episodes
        raw_items = self.fetch_all_episodes(drama_id, language=lang)

        episodes: List[MediaEpisode] = []
        direct_stream_candidates: List[str] = []

        for idx, item in enumerate(raw_items, start=1):
            drama_video_data = item.get("dramaInfo", {}).get("DramaVideoData", {}) if isinstance(item.get("dramaInfo"), dict) else {}
            ep_num = drama_video_data.get("EpisodeNumber") or idx
            trans_desc = drama_video_data.get("TranslatedDescription") or drama_video_data.get("translatedDescription")
            ep_desc = trans_desc or item.get("desc") or f"Episode {ep_num}"
            dur = item.get("video", {}).get("duration") or 0 if isinstance(item.get("video"), dict) else 0

            item_id = str(item.get("id") or "")
            author = item.get("author", {}).get("uniqueId") or "" if isinstance(item.get("author"), dict) else ""

            # Check for direct stream URLs
            ep_direct_url = ""
            video_obj = item.get("video", {}) if isinstance(item.get("video"), dict) else {}
            play_addr = video_obj.get("playAddr") or ""
            if play_addr and isinstance(play_addr, str) and play_addr.startswith("http"):
                ep_direct_url = play_addr
            else:
                bitrate_info = video_obj.get("bitrateInfo") or []
                if isinstance(bitrate_info, list):
                    for br in bitrate_info:
                        if isinstance(br, dict):
                            p_addr = br.get("PlayAddr") or br.get("playAddr") or {}
                            if isinstance(p_addr, dict):
                                urls = p_addr.get("UrlList") or p_addr.get("urlList") or []
                                for u in urls:
                                    if isinstance(u, str) and u.startswith("http"):
                                        ep_direct_url = u
                                        break
                        if ep_direct_url:
                            break

            if ep_direct_url:
                direct_stream_candidates.append(ep_direct_url)

            # Build canonical episode URL - prioritize permanent TikTok post URL
            author_handle = author or (item.get("author", {}).get("uniqueId") if isinstance(item.get("author"), dict) else "")
            if item_id:
                author_slug = f"@{author_handle}" if author_handle else "@tiktok"
                ep_url = f"https://www.tiktok.com/{author_slug}/video/{item_id}"
            elif ep_direct_url:
                ep_url = ep_direct_url
            else:
                ep_url = f"https://www.tiktok.com/shortdrama/episode/{drama_id}/{ep_num}"

            episodes.append(
                MediaEpisode(
                    episode_number=int(ep_num),
                    title=MetadataService.clean_title(ep_desc),
                    url=ep_url,
                    duration_seconds=int(dur) if dur else None,
                )
            )

        # 4. Check for syndicated full-series compilations
        if self.enable_syndication_search:
            clean_drama = self.clean_drama_title(series_title)
            compilations = self.find_syndicated_compilations(clean_drama)
            if compilations:
                episodes = compilations + episodes

        # Fallback if no episodes were discovered via API
        if not episodes:
            target_num = target_ep_num or 1
            episodes.append(
                MediaEpisode(
                    episode_number=target_num,
                    title=f"Episode {target_num}",
                    url=validated_url,
                )
            )

        # 5. Build standardized formats
        formats = [
            MediaFormat(
                format_id="best",
                resolution="Best Quality (Auto)",
                extension="mp4",
                note="Original video and audio",
                has_video=True,
                has_audio=True,
            ),
            MediaFormat(
                format_id="1080p",
                resolution="1080p HD",
                extension="mp4",
                note="High Definition (H.264)",
                has_video=True,
                has_audio=True,
            ),
            MediaFormat(
                format_id="720p",
                resolution="720p",
                extension="mp4",
                note="Standard HD (H.264)",
                has_video=True,
                has_audio=True,
            ),
            MediaFormat(
                format_id="bestaudio",
                resolution="Audio Only",
                extension="mp3",
                note="Audio track (MP3 / AAC)",
                has_video=False,
                has_audio=True,
            ),
        ]

        # If direct stream was extracted, place it first
        if direct_stream_candidates:
            formats.insert(
                0,
                MediaFormat(
                    format_id=direct_stream_candidates[0],
                    resolution="Direct Stream",
                    extension="mp4",
                    note="High speed direct video feed",
                    has_video=True,
                    has_audio=True,
                ),
            )

        display_title = series_title
        if target_ep_num:
            display_title = f"{series_title} - Episode {target_ep_num}"

        duration = int(drama_info.get("totalDuration") or 0) if drama_info.get("totalDuration") else None

        return MediaInfo(
            url=validated_url,
            title=MetadataService.clean_title(display_title),
            platform=self.platform_name,
            thumbnail_url=cover_url or None,
            duration_seconds=duration,
            formats=formats,
            episodes=episodes,
            is_playlist=len(episodes) > 1,
        )
