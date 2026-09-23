"""FlickReels platform extractor."""

from urllib.parse import urlparse
from app.extractors.drama_base import BaseDramaExtractor


class FlickReelsExtractor(BaseDramaExtractor):
    """Custom extractor for FlickReels short drama content."""

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "FlickReels"

    def can_handle(self, url: str) -> bool:
        """Return True if URL belongs to FlickReels."""
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "flickreels.com" in netloc or "flickreelsapp.com" in netloc

