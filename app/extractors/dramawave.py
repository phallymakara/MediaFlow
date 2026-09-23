"""DramaWave platform extractor."""

from urllib.parse import urlparse
from app.extractors.drama_base import BaseDramaExtractor


class DramaWaveExtractor(BaseDramaExtractor):
    """Custom extractor for DramaWave drama content."""

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "DramaWave"

    def can_handle(self, url: str) -> bool:
        """Return True if URL belongs to DramaWave."""
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "dramawave.com" in netloc

