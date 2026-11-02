"""Base extractor classes and media data models."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from app.core.errors import ExtractError
from app.core.media import MediaFormat, MediaInfo as CoreMediaInfo


class ExtractionError(ExtractError):
    """Raised when media extraction fails or encounters an unplayable source."""

    pass


@dataclass
class Variant:
    url: str
    quality: str = "unknown"
    bitrate: int = 0
    headers: dict = field(default_factory=dict)


@dataclass
class MediaInfo:
    site: str
    media_id: str
    title: str
    variants: list[Variant]
    is_hls: bool = False
    duration: float | None = None
    extra: dict = field(default_factory=dict)

    def to_core_media_info(self) -> CoreMediaInfo:
        """Convert backend MediaInfo to desktop CoreMediaInfo."""
        formats = [
            MediaFormat(
                format_id=f"{v.quality}_{i}",
                resolution=v.quality,
                extension="m3u8" if (self.is_hls or ".m3u8" in v.url) else "mp4",
                has_video=True,
                has_audio=True,
            )
            for i, v in enumerate(self.variants)
        ]
        return CoreMediaInfo(
            url=self.variants[0].url if self.variants else "",
            title=self.title,
            platform=self.site,
            duration_seconds=int(self.duration) if self.duration else None,
            formats=formats,
            episodes=[],
            is_playlist=False,
        )


class BaseExtractor(ABC):
    """Abstract base class for all media extractors."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the standard human-readable name of the platform."""
        pass

    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Return True if this extractor can handle the provided URL.

        Args:
            url: The media URL to evaluate.
        """
        pass

    @abstractmethod
    def extract(self, url: str) -> CoreMediaInfo:
        """Extract media metadata and stream information from the URL.

        Args:
            url: The media URL to extract.

        Returns:
            Normalized MediaInfo object.

        Raises:
            ExtractionError: If metadata extraction fails.
        """
        pass
