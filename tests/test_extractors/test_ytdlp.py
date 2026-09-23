"""Tests for YtDlpExtractor."""

from unittest.mock import MagicMock, patch
import pytest
import yt_dlp

from app.extractors.base import ExtractionError
from app.extractors.ytdlp import YtDlpExtractor


@pytest.fixture
def extractor() -> YtDlpExtractor:
    """Fixture providing a YtDlpExtractor instance."""
    return YtDlpExtractor()


def test_ytdlp_can_handle(extractor: YtDlpExtractor) -> None:
    """Verify URL detection for supported video domains and direct media files."""
    assert extractor.can_handle("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True
    assert extractor.can_handle("https://youtu.be/dQw4w9WgXcQ") is True
    assert extractor.can_handle("https://www.tiktok.com/@user/video/12345") is True
    assert extractor.can_handle("https://www.instagram.com/reel/C12345/") is True
    assert extractor.can_handle("https://x.com/user/status/12345") is True
    assert extractor.can_handle("https://twitter.com/user/status/12345") is True
    assert extractor.can_handle("https://v.redd.it/12345") is True
    assert extractor.can_handle("https://vimeo.com/12345") is True
    assert extractor.can_handle("https://example.com/stream/video.mp4") is True

    # Invalid URLs
    assert extractor.can_handle("") is False
    assert extractor.can_handle("ftp://example.com/video.mp4") is False
    assert extractor.can_handle("not_a_url") is False


def test_ytdlp_platform_name_resolution(extractor: YtDlpExtractor) -> None:
    """Verify extractor keys are mapped to clean platform names."""
    assert extractor._resolve_platform_name({"extractor_key": "Youtube"}, "https://youtube.com") == "YouTube"
    assert extractor._resolve_platform_name({"extractor_key": "TikTok"}, "https://tiktok.com") == "TikTok"
    assert extractor._resolve_platform_name({"extractor_key": "Instagram"}, "https://instagram.com") == "Instagram"
    assert extractor._resolve_platform_name({"extractor_key": "Twitter"}, "https://x.com") == "X (Twitter)"
    assert extractor._resolve_platform_name({"extractor_key": "Reddit"}, "https://reddit.com") == "Reddit"


def test_ytdlp_format_normalization(extractor: YtDlpExtractor) -> None:
    """Verify raw yt-dlp format dictionaries are grouped and deduplicated."""
    raw_formats = [
        {"format_id": "137", "ext": "mp4", "height": 1080, "vcodec": "avc1", "acodec": "none", "fps": 60, "tbr": 4000},
        {"format_id": "248", "ext": "webm", "height": 1080, "vcodec": "vp9", "acodec": "none", "fps": 30, "tbr": 3000},
        {"format_id": "22", "ext": "mp4", "height": 720, "vcodec": "avc1", "acodec": "mp4a", "fps": 30, "tbr": 2000},
        {"format_id": "140", "ext": "m4a", "height": None, "vcodec": "none", "acodec": "mp4a", "abr": 128},
    ]

    normalized = extractor._normalize_formats(raw_formats)

    # Must contain "Best Available" at index 0
    assert normalized[0].format_id == "bestvideo+bestaudio/best"

    # Resolutions should be deduplicated (only one 1080p, one 720p)
    resolutions = [f.resolution for f in normalized]
    assert resolutions.count("1080p") == 1
    assert resolutions.count("720p") == 1
    assert "Audio Only" in resolutions


@patch("yt_dlp.YoutubeDL")
def test_ytdlp_extract_success(mock_ydl_cls: MagicMock, extractor: YtDlpExtractor) -> None:
    """Verify successful extraction populates MediaInfo correctly."""
    mock_instance = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_instance

    mock_instance.extract_info.return_value = {
        "title": "Amazing Documentary &amp; Nature",
        "duration": 3600,
        "extractor_key": "Youtube",
        "thumbnail": "https://example.com/thumb.jpg",
        "formats": [
            {"format_id": "22", "ext": "mp4", "height": 720, "vcodec": "avc1", "acodec": "mp4a", "fps": 30},
        ],
    }

    media_info = extractor.extract("https://youtube.com/watch?v=123")

    assert media_info.title == "Amazing Documentary & Nature"
    assert media_info.duration_seconds == 3600
    assert media_info.platform == "YouTube"
    assert media_info.thumbnail_url == "https://example.com/thumb.jpg"
    assert len(media_info.formats) > 0
    assert media_info.is_playlist is False


@patch("yt_dlp.YoutubeDL")
def test_ytdlp_extract_private_video_error(mock_ydl_cls: MagicMock, extractor: YtDlpExtractor) -> None:
    """Verify private video errors are translated into clean ExtractionError messages."""
    mock_instance = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_instance
    mock_instance.extract_info.side_effect = yt_dlp.utils.DownloadError("Private video. Sign in to watch.")

    with pytest.raises(ExtractionError) as exc_info:
        extractor.extract("https://youtube.com/watch?v=private")

    assert "private" in str(exc_info.value).lower()


@patch("yt_dlp.YoutubeDL")
def test_ytdlp_extract_unavailable_error(mock_ydl_cls: MagicMock, extractor: YtDlpExtractor) -> None:
    """Verify unavailable video errors are translated into clean ExtractionError messages."""
    mock_instance = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_instance
    mock_instance.extract_info.side_effect = yt_dlp.utils.DownloadError("Video unavailable: video has been removed")

    with pytest.raises(ExtractionError) as exc_info:
        extractor.extract("https://youtube.com/watch?v=removed")

    assert "unavailable" in str(exc_info.value).lower()
