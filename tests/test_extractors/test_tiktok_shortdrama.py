"""Unit tests for TikTok Short Drama extractor and integration."""

from unittest.mock import MagicMock
import httpx
import pytest

from app.core.extractor_registry import get_default_registry
from app.extractors.base import ExtractionError
from app.extractors.tiktok_shortdrama import TikTokShortDramaExtractor
from app.extractors.ytdlp import YtDlpExtractor


MOCK_DRAMA_DETAIL = {
    "dramaInfo": {
        "dramaID": "7684287182416417813",
        "dramaName": "The CEO's Fishmonger",
        "description": "A female CEO pretends to be poor to go on blind dates.",
        "numVideos": 44,
        "totalDuration": "2958",
        "cover": {
            "urlList": ["https://p16-common-sign.tiktokcdn.com/cover.jpg"]
        },
    }
}

MOCK_EPISODE_PAGE_1 = {
    "hasMore": True,
    "cursor": "30",
    "itemList": [
        {
            "id": "7684287404030643477",
            "desc": "Episode 1",
            "author": {"uniqueId": "destinystonedrama"},
            "video": {
                "duration": 70,
                "playAddr": "https://v16-webapp-prime.tiktok.com/stream_ep1.mp4",
            },
            "dramaInfo": {
                "DramaVideoData": {"EpisodeNumber": 1}
            }
        },
        {
            "id": "7684287393393904917",
            "desc": "Episode 2",
            "author": {"uniqueId": "destinystonedrama"},
            "video": {
                "duration": 65,
                "playAddr": "https://v16-webapp-prime.tiktok.com/stream_ep2.mp4",
            },
            "dramaInfo": {
                "DramaVideoData": {"EpisodeNumber": 2}
            }
        },
    ]
}

MOCK_EPISODE_PAGE_2 = {
    "hasMore": False,
    "cursor": "",
    "itemList": [
        {
            "id": "7684287396866788629",
            "desc": "Episode 3",
            "author": {"uniqueId": "destinystonedrama"},
            "video": {
                "duration": 80,
                "playAddr": "https://v16-webapp-prime.tiktok.com/stream_ep3.mp4",
            },
            "dramaInfo": {
                "DramaVideoData": {"EpisodeNumber": 3}
            }
        }
    ]
}


def test_tiktok_shortdrama_can_handle() -> None:
    """Verify URL pattern matching for TikTok Short Drama extractor."""
    extractor = TikTokShortDramaExtractor(enable_syndication_search=False)

    # Valid short drama patterns
    assert extractor.can_handle("https://www.tiktok.com/shortdrama/episode/7684287182416417813") is True
    assert extractor.can_handle("https://www.tiktok.com/shortdrama/episode/7684287182416417813/1") is True
    assert extractor.can_handle("https://www.tiktok.com/shortdrama/episode/en/7684287182416417813/1") is True
    assert extractor.can_handle("https://www.tiktok.com/shortdrama/7684287182416417813") is True
    assert extractor.can_handle("https://m.tiktok.com/shortdrama/episode/7684287182416417813/5") is True

    # Standard TikTok videos should NOT be handled by shortdrama extractor
    assert extractor.can_handle("https://www.tiktok.com/@destinystonedrama/video/7684287404030643477") is False
    assert extractor.can_handle("https://www.tiktok.com/@user/video/123456789") is False

    # Other sites should return False
    assert extractor.can_handle("https://www.youtube.com/watch?v=123") is False
    assert extractor.can_handle("https://www.dramabox.com/drama/123") is False
    assert extractor.can_handle("") is False


def test_ytdlp_can_handle_excludes_shortdrama() -> None:
    """Verify YtDlpExtractor excludes TikTok shortdrama URLs to prevent Unsupported URL crashes."""
    ytdlp = YtDlpExtractor()

    # Short drama URLs must NOT be handled by Generic Video / YtDlpExtractor
    assert ytdlp.can_handle("https://www.tiktok.com/shortdrama/episode/7684287182416417813") is False
    assert ytdlp.can_handle("https://www.tiktok.com/shortdrama/episode/7684287182416417813/1") is False

    # Standard TikTok videos SHOULD be handled by YtDlpExtractor
    assert ytdlp.can_handle("https://www.tiktok.com/@destinystonedrama/video/7684287404030643477") is True
    assert ytdlp.can_handle("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True


def test_extract_drama_id_and_episode() -> None:
    """Verify parsing drama ID and episode number from various URL structures."""
    extractor = TikTokShortDramaExtractor(enable_syndication_search=False)

    drama_id, ep = extractor.extract_drama_id_and_episode("https://www.tiktok.com/shortdrama/episode/7684287182416417813")
    assert drama_id == "7684287182416417813"
    assert ep is None

    drama_id, ep = extractor.extract_drama_id_and_episode("https://www.tiktok.com/shortdrama/episode/7684287182416417813/5")
    assert drama_id == "7684287182416417813"
    assert ep == 5

    drama_id, ep = extractor.extract_drama_id_and_episode("https://www.tiktok.com/shortdrama/episode/en/7684287182416417813/12")
    assert drama_id == "7684287182416417813"
    assert ep == 12

    drama_id, ep = extractor.extract_drama_id_and_episode("https://www.tiktok.com/shortdrama/7684287182416417813")
    assert drama_id == "7684287182416417813"
    assert ep is None


def test_tiktok_shortdrama_extract_mocked() -> None:
    """Verify complete metadata extraction and pagination with mocked client."""
    mock_client = MagicMock(spec=httpx.Client)

    def mock_get(url, params=None, headers=None):
        resp = MagicMock(spec=httpx.Response)
        resp.raise_for_status = MagicMock()
        if "/api/drama/detail/" in url:
            resp.json.return_value = MOCK_DRAMA_DETAIL
        elif "/api/drama/episode/item_list/" in url:
            cursor = params.get("cursor", "0") if params else "0"
            if cursor == "0":
                resp.json.return_value = MOCK_EPISODE_PAGE_1
            else:
                resp.json.return_value = MOCK_EPISODE_PAGE_2
        return resp

    mock_client.get.side_effect = mock_get

    extractor = TikTokShortDramaExtractor(client=mock_client, enable_syndication_search=False)
    info = extractor.extract("https://www.tiktok.com/shortdrama/episode/7684287182416417813")

    assert info.platform == "TikTok Short Drama"
    assert info.title == "The CEO's Fishmonger"
    assert info.thumbnail_url == "https://p16-common-sign.tiktokcdn.com/cover.jpg"
    assert info.duration_seconds == 2958
    assert info.is_playlist is True
    assert len(info.episodes) == 3

    assert info.episodes[0].episode_number == 1
    assert info.episodes[0].title == "Episode 1"
    assert info.episodes[0].url == "https://www.tiktok.com/@destinystonedrama/video/7684287404030643477"
    assert info.episodes[0].duration_seconds == 70

    assert info.episodes[1].episode_number == 2
    assert info.episodes[1].title == "Episode 2"
    assert info.episodes[1].url == "https://www.tiktok.com/@destinystonedrama/video/7684287393393904917"

    assert info.episodes[2].episode_number == 3
    assert info.episodes[2].title == "Episode 3"
    assert info.episodes[2].url == "https://www.tiktok.com/@destinystonedrama/video/7684287396866788629"

    # Verify standard formats are present
    format_ids = [f.format_id for f in info.formats]
    assert "best" in format_ids
    assert "1080p" in format_ids
    assert "720p" in format_ids
    assert "bestaudio" in format_ids


def test_registry_finds_tiktok_shortdrama() -> None:
    """Verify default ExtractorRegistry routes TikTok shortdrama URLs with priority over generic yt-dlp."""
    registry = get_default_registry()

    url = "https://www.tiktok.com/shortdrama/episode/7684287182416417813/1"
    extractor = registry.find_extractor(url)

    assert extractor is not None
    assert isinstance(extractor, TikTokShortDramaExtractor)
    assert extractor.platform_name == "TikTok Short Drama"

    # Regular TikTok video should route to YtDlpExtractor
    regular_url = "https://www.tiktok.com/@destinystonedrama/video/7684287404030643477"
    reg_extractor = registry.find_extractor(regular_url)
    assert reg_extractor is not None
    assert isinstance(reg_extractor, YtDlpExtractor)
