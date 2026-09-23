"""StardustTV platform extractor with multi-mirror support."""

from typing import List
from urllib.parse import urlparse

from app.extractors.drama_base import BaseDramaExtractor


class StardustTVExtractor(BaseDramaExtractor):
    """Custom extractor for StardustTV drama content with automated mirror rotation."""

    canonical_id_patterns: List[str] = [
        r'/(?:drama|play|watch)/([a-zA-Z0-9_-]+)',
    ]
    mirror_templates: List[str] = [
        "https://stardust.tv/play/{id}",
        "https://stardusttv.co/drama/{id}",
    ]

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "StardustTV"

    def can_handle(self, url: str) -> bool:
        """Return True if URL belongs to StardustTV or its mirrors."""
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "stardusttv.com" in netloc or "stardust.tv" in netloc or "stardusttv.co" in netloc

