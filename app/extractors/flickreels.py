"""FlickReels platform extractor with multi-mirror support."""

from typing import List
from urllib.parse import urlparse

from app.extractors.drama_base import BaseDramaExtractor


class FlickReelsExtractor(BaseDramaExtractor):
    """Custom extractor for FlickReels short drama content with automated mirror rotation."""

    canonical_id_patterns: List[str] = [
        r'/(?:series|watch|show)/([a-zA-Z0-9_-]+)',
    ]
    mirror_templates: List[str] = [
        "https://flickreelsapp.com/watch/{id}",
        "https://flickreels.co/series/{id}",
    ]

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "FlickReels"

    def can_handle(self, url: str) -> bool:
        """Return True if URL belongs to FlickReels or its mirrors."""
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "flickreels.com" in netloc or "flickreelsapp.com" in netloc or "flickreels.co" in netloc

