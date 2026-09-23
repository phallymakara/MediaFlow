"""DramaWave platform extractor with multi-mirror support."""

from typing import List
from urllib.parse import urlparse

from app.extractors.drama_base import BaseDramaExtractor


class DramaWaveExtractor(BaseDramaExtractor):
    """Custom extractor for DramaWave drama content with automated mirror rotation."""

    canonical_id_patterns: List[str] = [
        r'/(?:show|watch|drama)/([a-zA-Z0-9_-]+)',
    ]
    mirror_templates: List[str] = [
        "https://dramawaveapp.com/watch/{id}",
        "https://dramawave.co/show/{id}",
    ]

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "DramaWave"

    def can_handle(self, url: str) -> bool:
        """Return True if URL belongs to DramaWave or its mirrors."""
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "dramawave.com" in netloc or "dramawaveapp.com" in netloc or "dramawave.co" in netloc

