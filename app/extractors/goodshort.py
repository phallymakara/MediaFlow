"""GoodShort platform extractor."""

from urllib.parse import urlparse
from app.extractors.drama_base import BaseDramaExtractor


class GoodShortExtractor(BaseDramaExtractor):
    """Custom extractor for GoodShort drama content."""

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "GoodShort"

    def can_handle(self, url: str) -> bool:
        """Return True if URL belongs to GoodShort."""
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "goodshort.com" in netloc

