"""GoodShort platform extractor with multi-mirror support."""

from typing import List
from urllib.parse import urlparse

from app.extractors.drama_base import BaseDramaExtractor


class GoodShortExtractor(BaseDramaExtractor):
    """Custom extractor for GoodShort drama content with automated mirror rotation."""

    canonical_id_patterns: List[str] = [
        r'/(?:book|drama|chapter)/([a-zA-Z0-9_-]+)',
    ]
    mirror_templates: List[str] = [
        "https://goodshortapp.com/drama/{id}",
        "https://goodshort.co/book/{id}",
    ]

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "GoodShort"

    def can_handle(self, url: str) -> bool:
        """Return True if URL belongs to GoodShort or its mirrors."""
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "goodshort.com" in netloc or "goodshortapp.com" in netloc or "goodshort.co" in netloc

