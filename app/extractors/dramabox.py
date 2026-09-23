"""DramaBox platform extractor."""

from typing import Optional
from urllib.parse import urlparse

from app.extractors.drama_base import BaseDramaExtractor


class DramaBoxExtractor(BaseDramaExtractor):
    """Custom extractor for DramaBox short drama content."""

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "DramaBox"

    def can_handle(self, url: str) -> bool:
        """Return True if URL belongs to DramaBox."""
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "dramabox.com" in netloc or "dramaboxdb.com" in netloc

