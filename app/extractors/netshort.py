"""NetShort platform extractor."""

from urllib.parse import urlparse
from app.extractors.drama_base import BaseDramaExtractor


class NetShortExtractor(BaseDramaExtractor):
    """Custom extractor for NetShort drama content."""

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "NetShort"

    def can_handle(self, url: str) -> bool:
        """Return True if URL belongs to NetShort."""
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "netshort.com" in netloc or "netshortapp.com" in netloc

