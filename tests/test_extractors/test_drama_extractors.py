"""Tests for custom short drama extractors."""

from unittest.mock import MagicMock
import httpx
import pytest

from app.core.extractor_registry import get_default_registry
from app.extractors.base import ExtractionError
from app.extractors.dramabox import DramaBoxExtractor
from app.extractors.dramawave import DramaWaveExtractor
from app.extractors.flickreels import FlickReelsExtractor
from app.extractors.freereels import FreeReelsExtractor
from app.extractors.goodshort import GoodShortExtractor
from app.extractors.netshort import NetShortExtractor
from app.extractors.stardusttv import StardustTVExtractor


SAMPLE_DRAMA_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta property="og:title" content="Billionaire's Secret Bride &amp; Revenge" />
    <meta property="og:image" content="https://example.com/poster.jpg" />
    <meta property="og:description" content="A thrilling romance drama." />
</head>
<body>
    <h1>Billionaire's Secret Bride</h1>
    <video src="https://example.com/streams/ep1.mp4"></video>
    <div class="episodes">
        <a href="/watch/drama-123/ep-1">Episode 1</a>
        <a href="/watch/drama-123/ep-2">Episode 2</a>
        <a href="/watch/drama-123/ep-3">Episode 3</a>
    </div>
</body>
</html>
"""


def test_drama_can_handle() -> None:
    """Verify domain pattern matching across all 7 drama platforms."""
    assert DramaBoxExtractor().can_handle("https://www.dramabox.com/drama/123") is True
    assert DramaBoxExtractor().can_handle("https://dramaboxdb.com/play/456") is True

    assert NetShortExtractor().can_handle("https://netshort.com/watch/1") is True
    assert NetShortExtractor().can_handle("https://app.netshortapp.com/v/2") is True

    assert FlickReelsExtractor().can_handle("https://flickreels.com/series/3") is True
    assert FlickReelsExtractor().can_handle("https://flickreelsapp.com/series/4") is True

    assert StardustTVExtractor().can_handle("https://stardusttv.com/drama/5") is True
    assert StardustTVExtractor().can_handle("https://stardust.tv/drama/6") is True

    assert GoodShortExtractor().can_handle("https://goodshort.com/book/7") is True

    assert DramaWaveExtractor().can_handle("https://dramawave.com/show/8") is True

    assert FreeReelsExtractor().can_handle("https://freereels.com/detail/9") is True
    assert FreeReelsExtractor().can_handle("https://freereelsapp.com/detail/10") is True

    # Other URLs should not match drama extractors
    assert DramaBoxExtractor().can_handle("https://youtube.com/watch?v=123") is False
    assert NetShortExtractor().can_handle("https://tiktok.com/@user") is False


def test_drama_extraction_with_mock_client() -> None:
    """Verify HTML parsing extracts title, thumbnail, streams, and episodes correctly."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.text = SAMPLE_DRAMA_HTML
    mock_client.get.return_value = mock_response

    extractor = DramaBoxExtractor(client=mock_client)
    media_info = extractor.extract("https://www.dramabox.com/watch/drama-123")

    assert media_info.title == "Billionaire's Secret Bride & Revenge"
    assert media_info.platform == "DramaBox"
    assert media_info.thumbnail_url == "https://example.com/poster.jpg"
    assert len(media_info.formats) > 0
    assert len(media_info.episodes) == 3
    assert media_info.episodes[0].episode_number == 1
    assert media_info.episodes[1].episode_number == 2
    assert media_info.episodes[2].episode_number == 3
    assert media_info.is_playlist is True


def test_drama_extraction_http_404_error() -> None:
    """Verify HTTP 404 triggers a clean ExtractionError."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 404

    http_err = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)
    mock_response.raise_for_status.side_effect = http_err
    mock_client.get.return_value = mock_response

    extractor = NetShortExtractor(client=mock_client)
    with pytest.raises(ExtractionError) as exc_info:
        extractor.extract("https://netshort.com/missing-drama")

    assert "not found" in str(exc_info.value).lower()


def test_drama_extraction_http_403_restricted() -> None:
    """Verify HTTP 403 triggers a restricted access ExtractionError."""
    mock_client = MagicMock(spec=httpx.Client)
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 403

    http_err = httpx.HTTPStatusError("Forbidden", request=MagicMock(), response=mock_response)
    mock_response.raise_for_status.side_effect = http_err
    mock_client.get.return_value = mock_response

    extractor = GoodShortExtractor(client=mock_client)
    with pytest.raises(ExtractionError) as exc_info:
        extractor.extract("https://goodshort.com/restricted-drama")

    assert "restricted" in str(exc_info.value).lower()


def test_default_registry_routes_drama_platforms() -> None:
    """Verify default registry correctly prioritizes custom drama extractors over yt-dlp."""
    registry = get_default_registry()

    dramabox_match = registry.find_extractor("https://www.dramabox.com/watch/123")
    assert isinstance(dramabox_match, DramaBoxExtractor)

    netshort_match = registry.find_extractor("https://netshort.com/play/456")
    assert isinstance(netshort_match, NetShortExtractor)

    goodshort_match = registry.find_extractor("https://goodshort.com/book/789")
    assert isinstance(goodshort_match, GoodShortExtractor)

    # General video still falls back to yt-dlp
    youtube_match = registry.find_extractor("https://youtube.com/watch?v=dQw4w9WgXcQ")
    assert youtube_match.platform_name == "Generic Video"
