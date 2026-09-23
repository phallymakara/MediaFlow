"""FreeReels platform extractor."""

from urllib.parse import urlparse
from app.extractors.drama_base import BaseDramaExtractor


class FreeReelsExtractor(BaseDramaExtractor):
    """Custom extractor for FreeReels drama content."""

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "FreeReels"

    def can_handle(self, url: str) -> bool:
        """Return True if URL belongs to FreeReels."""
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "freereels.com" in netloc or "freereelsapp.com" in netloc

