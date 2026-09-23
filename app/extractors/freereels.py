"""FreeReels platform extractor with multi-mirror support."""

from typing import List
from urllib.parse import urlparse

from app.extractors.drama_base import BaseDramaExtractor


class FreeReelsExtractor(BaseDramaExtractor):
    """Custom extractor for FreeReels drama content with automated mirror rotation."""

    canonical_id_patterns: List[str] = [
        r'/(?:detail|watch|series)/([a-zA-Z0-9_-]+)',
    ]
    mirror_templates: List[str] = [
        "https://freereelsapp.com/watch/{id}",
        "https://freereels.cc/detail/{id}",
    ]

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "FreeReels"

    def can_handle(self, url: str) -> bool:
        """Return True if URL belongs to FreeReels or its mirrors."""
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "freereels.com" in netloc or "freereelsapp.com" in netloc or "freereels.cc" in netloc

