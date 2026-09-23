"""StardustTV platform extractor."""

from urllib.parse import urlparse
from app.extractors.drama_base import BaseDramaExtractor


class StardustTVExtractor(BaseDramaExtractor):
    """Custom extractor for StardustTV drama content."""

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "StardustTV"

    def can_handle(self, url: str) -> bool:
        """Return True if URL belongs to StardustTV."""
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "stardusttv.com" in netloc or "stardust.tv" in netloc

