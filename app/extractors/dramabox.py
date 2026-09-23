"""DramaBox platform extractor with mirror resolution support."""

from typing import List, Optional
from urllib.parse import urlparse

from app.extractors.drama_base import BaseDramaExtractor


class DramaBoxExtractor(BaseDramaExtractor):
    """Custom extractor for DramaBox short drama content with fallback mirror support."""

    canonical_id_patterns: List[str] = [
        r'/(?:drama|watch|movie|book|series)/(\d+)',
    ]
    mirror_templates: List[str] = [
        "https://dramaboxdb.com/watch/{id}",
    ]

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        return "DramaBox"

    def can_handle(self, url: str) -> bool:
        """Return True if URL belongs to DramaBox or its indexed mirrors."""
        if not url or not url.strip():
            return False
        netloc = urlparse(url.strip()).netloc.lower()
        return "dramabox.com" in netloc or "dramaboxdb.com" in netloc

    def extract_drama_id(self, url: str) -> Optional[str]:
        """Extract canonical drama ID (alias for extract_canonical_id)."""
        return self.extract_canonical_id(url)

