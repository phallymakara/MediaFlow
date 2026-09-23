"""Base extractor abstract class."""

from abc import ABC, abstractmethod
from app.core.media import MediaInfo


class ExtractionError(Exception):
    """Raised when media extraction fails or encounters an unplayable source."""

    pass


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
    def extract(self, url: str) -> MediaInfo:
        """Extract media metadata and stream information from the URL.

        Args:
            url: The media URL to extract.

        Returns:
            Normalized MediaInfo object.

        Raises:
            ExtractionError: If metadata extraction fails.
        """
        pass

