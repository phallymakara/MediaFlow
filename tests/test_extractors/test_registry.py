"""Tests for ExtractorRegistry."""

import pytest
from app.core.extractor_registry import ExtractorRegistry, get_default_registry
from app.core.media import MediaInfo
from app.extractors.base import BaseExtractor, ExtractionError


class DummyCustomExtractor(BaseExtractor):
    """Mock extractor for testing priority routing."""

    @property
    def platform_name(self) -> str:
        return "CustomPlatform"

    def can_handle(self, url: str) -> bool:
        return "customplatform.com" in url

    def extract(self, url: str) -> MediaInfo:
        return MediaInfo(
            url=url,
            title="Custom Platform Video",
            platform=self.platform_name,
        )


class DummyFallbackExtractor(BaseExtractor):
    """Mock fallback extractor."""

    @property
    def platform_name(self) -> str:
        return "Fallback"

    def can_handle(self, url: str) -> bool:
        return True

    def extract(self, url: str) -> MediaInfo:
        return MediaInfo(
            url=url,
            title="Fallback Video",
            platform=self.platform_name,
        )


def test_registry_registration_and_priority() -> None:
    """Verify high-priority extractors are tested before fallback extractors."""
    registry = ExtractorRegistry()

    fallback = DummyFallbackExtractor()
    custom = DummyCustomExtractor()

    # Register fallback first with lower priority (higher number)
    registry.register(fallback, priority=100)
    # Register custom with higher priority (lower number)
    registry.register(custom, priority=10)

    # For a customplatform URL, the custom extractor should be selected
    matched = registry.find_extractor("https://customplatform.com/watch?v=123")
    assert matched is custom
    assert matched.platform_name == "CustomPlatform"

    # For another URL, fallback should be selected
    matched_fallback = registry.find_extractor("https://otherplatform.com/video")
    assert matched_fallback is fallback


def test_registry_extract_info() -> None:
    """Verify registry routes extraction call and returns normalized MediaInfo."""
    registry = ExtractorRegistry()
    registry.register(DummyCustomExtractor(), priority=10)

    info = registry.extract_info("https://customplatform.com/video/456")
    assert info.title == "Custom Platform Video"
    assert info.platform == "CustomPlatform"
    assert info.url == "https://customplatform.com/video/456"


def test_registry_unsupported_url_raises_error() -> None:
    """Verify registry raises ExtractionError when no extractor can handle the URL."""
    registry = ExtractorRegistry()
    # No extractors registered
    with pytest.raises(ExtractionError):
        registry.extract_info("https://unknown.com/video")


def test_registry_supported_platforms() -> None:
    """Verify distinct supported platform names are returned."""
    registry = ExtractorRegistry()
    registry.register(DummyCustomExtractor(), priority=10)
    registry.register(DummyFallbackExtractor(), priority=100)

    platforms = registry.supported_platforms()
    assert "CustomPlatform" in platforms
    assert "Fallback" in platforms


def test_get_default_registry() -> None:
    """Verify default registry includes standard YtDlpExtractor."""
    registry = get_default_registry()
    assert len(registry.supported_platforms()) > 0
    extractor = registry.find_extractor("https://youtube.com/watch?v=dQw4w9WgXcQ")
    assert extractor is not None
