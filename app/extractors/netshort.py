"""NetShort platform extractor with multi-mirror support."""

from typing import List
from urllib.parse import urlparse

from app.extractors.drama_base import BaseDramaExtractor


class NetShortExtractor(BaseDramaExtractor):
    """Custom extractor for NetShort drama content with automated mirror rotation."""

    canonical_id_patterns: List[str] = [
        r'/(?:watch|drama|v|play)/([a-zA-Z0-9_-]+)',
    ]
    mirror_templates: List[str] = [
        "https://app.netshortapp.com/v/{id}",
        "https://netshortdb.com/watch/{id}",
    ]

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "NetShort"

    def can_handle(self, url: str) -> bool:
        """Return True if URL belongs to NetShort or its mirrors."""
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "netshort.com" in netloc or "netshortapp.com" in netloc or "netshortdb.com" in netloc

