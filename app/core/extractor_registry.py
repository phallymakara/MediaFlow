"""Extractor registry for discovering and routing media extractors."""

import logging
from typing import List, Optional, Tuple

from app.core.media import MediaInfo
from app.extractors.base import BaseExtractor, ExtractionError
from app.extractors.dramabox import DramaBoxExtractor
from app.extractors.dramawave import DramaWaveExtractor
from app.extractors.flickreels import FlickReelsExtractor
from app.extractors.freereels import FreeReelsExtractor
from app.extractors.goodshort import GoodShortExtractor
from app.extractors.netshort import NetShortExtractor
from app.extractors.stardusttv import StardustTVExtractor
from app.extractors.ytdlp import YtDlpExtractor
from app.services.network import redact_url_for_logging, validate_outbound_url

logger = logging.getLogger(__name__)


class ExtractorRegistry:
    """Registry maintaining available media extractors and URL pattern matching."""

    def __init__(self) -> None:
        """Initialize empty extractor registry."""
        self._extractors: List[Tuple[int, BaseExtractor]] = []

    def register(self, extractor: BaseExtractor, priority: int = 100) -> None:
        """Register an extractor with a priority ranking.

        Lower priority values execute first. Dedicated/custom extractors should
        use a priority between 1-50, while universal fallback extractors use 100+.

        Args:
            extractor: BaseExtractor instance to register.
            priority: Integer priority (default 100).
        """
        self._extractors.append((priority, extractor))
        self._extractors.sort(key=lambda item: item[0])
        logger.debug(
            "Registered extractor '%s' with priority %d",
            extractor.platform_name,
            priority,
        )

    def find_extractor(self, url: str) -> Optional[BaseExtractor]:
        """Find the highest-priority extractor capable of handling the URL.

        Args:
            url: The media URL to test.

        Returns:
            Matching BaseExtractor instance, or None if no extractor handles it.
        """
        if not url or not url.strip():
            return None

        clean_url = url.strip()
        for _, extractor in self._extractors:
            try:
                if extractor.can_handle(clean_url):
                    return extractor
            except Exception as exc:
                logger.warning(
                    "Error checking can_handle for extractor '%s': %s",
                    extractor.platform_name,
                    exc,
                )

        return None

    def extract_info(self, url: str) -> MediaInfo:
        """Find matching extractor and retrieve normalized media metadata.

        Args:
            url: Media URL to extract.

        Returns:
            Normalized MediaInfo object.

        Raises:
            ExtractionError: If no extractor matches or extraction fails.
        """
        try:
            validated_url = validate_outbound_url(url)
        except ValueError as exc:
            logger.warning("Rejected unsafe URL: %s", exc)
            raise ExtractionError(f"Cannot extract from unsafe URL: {exc}") from exc

        extractor = self.find_extractor(validated_url)
        safe_url = redact_url_for_logging(validated_url)
        if not extractor:
            logger.warning("No matching extractor found for URL: %s", safe_url)
            raise ExtractionError("No suitable extractor found for this URL.")

        logger.info(
            "Extracting media using '%s' for URL: %s",
            extractor.platform_name,
            safe_url,
        )
        return extractor.extract(validated_url)

    def supported_platforms(self) -> List[str]:
        """Return distinct names of registered platforms.

        Returns:
            List of platform name strings.
        """
        seen: set = set()
        platforms: List[str] = []
        for _, extractor in self._extractors:
            name = extractor.platform_name
            if name not in seen:
                seen.add(name)
                platforms.append(name)
        return platforms


def get_default_registry() -> ExtractorRegistry:
    """Create and configure the default ExtractorRegistry with standard extractors.

    Returns:
        Configured ExtractorRegistry instance.
    """
    registry = ExtractorRegistry()

    # Register custom short drama extractors with high priority (20-26)
    registry.register(DramaBoxExtractor(), priority=20)
    registry.register(NetShortExtractor(), priority=21)
    registry.register(FlickReelsExtractor(), priority=22)
    registry.register(StardustTVExtractor(), priority=23)
    registry.register(GoodShortExtractor(), priority=24)
    registry.register(DramaWaveExtractor(), priority=25)
    registry.register(FreeReelsExtractor(), priority=26)

    # Register yt-dlp as universal fallback with default priority (100)
    registry.register(YtDlpExtractor(), priority=100)

    return registry

