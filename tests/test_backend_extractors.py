import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.extractors.base import MediaInfo, Variant
from app.extractors import douyin, kuaishou, bilibili, dramabox, reelshort, shortmax
from app.core.errors import ExtractError


def test_douyin_build_variants():
    sample_item = {
        "aweme_id": "7123456789012345678",
        "desc": "Test Douyin Video Description",
        "author": {"nickname": "CreatorName"},
        "video": {
            "bit_rate": [
                {
                    "gear_name": "1080p",
                    "bit_rate": 2500000,
                    "play_addr": {"url_list": ["https://aweme.snssdk.com/playwm/?video_id=v02001"]},
                },
                {
                    "gear_name": "720p",
                    "bit_rate": 1200000,
                    "play_addr": {"url_list": ["https://aweme.snssdk.com/playwm/?video_id=v02002"]},
                },
            ]
        },
    }

    info = douyin._build(sample_item)
    assert info.site == "douyin"
    assert info.media_id == "7123456789012345678"
    assert info.title == "Test Douyin Video Description"
    assert len(info.variants) == 2
    # Verify de-watermarking replaced playwm with play
    assert "playwm" not in info.variants[0].url
    assert "play" in info.variants[0].url
    assert info.variants[0].bitrate == 2500000
    assert info.variants[0].headers == {"Referer": "https://www.douyin.com/"}
    assert info.extra.get("author") == "CreatorName"

    # Test conversion to desktop CoreMediaInfo
    core_info = info.to_core_media_info()
    assert core_info.platform == "douyin"
    assert len(core_info.formats) == 2


def test_douyin_parse_id():
    assert douyin.parse_id("https://www.douyin.com/video/7123456789012345678") == "7123456789012345678"
    assert douyin.parse_id("https://www.douyin.com/note/7123456789012345679") == "7123456789012345679"
    assert douyin.parse_id("https://v.douyin.com/xyz123/") == ""


def test_kuaishou_parse_id():
    assert kuaishou._parse("https://www.kuaishou.com/short-video/3xabcdefghij12") == "3xabcdefghij12"
    assert kuaishou._parse("https://www.kuaishou.com/photo/3xabcdefghij12") == "3xabcdefghij12"
    with pytest.raises(ExtractError):
        kuaishou._parse("https://example.com/invalid")


@pytest.mark.asyncio
async def test_kuaishou_extract_success():
    mock_json = {
        "photo": {
            "caption": "Funny Kuaishou Clip",
            "mainMvUrls": [{"url": "https://kuaishou.com/mv1.mp4"}],
            "manifest": {
                "adaptationSet": [
                    {
                        "representation": [
                            {"url": "https://kuaishou.com/rep1.mp4"}
                        ]
                    }
                ]
            },
        }
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_json
    mock_resp.raise_for_status = lambda: None

    with patch("app.extractors.kuaishou.get", new=AsyncMock(return_value=mock_resp)):
        info = await kuaishou.extract("https://www.kuaishou.com/short-video/3xabcdef123456")
        assert info.site == "kuaishou"
        assert info.media_id == "3xabcdef123456"
        assert info.title == "Funny Kuaishou Clip"
        assert len(info.variants) == 2
        assert info.variants[0].url == "https://kuaishou.com/mv1.mp4"
        assert info.variants[1].url == "https://kuaishou.com/rep1.mp4"


@pytest.mark.asyncio
async def test_bilibili_audio_helper():
    sample_dash = {
        "dash": {
            "audio": [
                {"baseUrl": "https://bili.com/audio_low.m4a", "id": 30216},
                {"baseUrl": "https://bili.com/audio_high.m4a", "id": 30280},
            ]
        }
    }
    audios = bilibili._audio(sample_dash)
    assert len(audios) == 2
    assert audios[0]["id"] == 30280  # Sorted highest quality first
    assert audios[1]["id"] == 30216


@pytest.mark.asyncio
async def test_dramabox_api():
    mock_data = {
        "data": {
            "episodeList": [
                {"episodeId": 101, "title": "Ep 1", "isFree": True, "videoUrl": "https://cdn.dramabox.com/ep1.m3u8"},
                {"episodeId": 102, "title": "Ep 2", "isFree": True, "videoUrl": "https://cdn.dramabox.com/ep2.m3u8"},
            ]
        }
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_data

    with patch("app.extractors.dramabox.get", new=AsyncMock(return_value=mock_resp)):
        info = await dramabox._api("book999", "https://dramaboxdb.com/watch/book999", {})
        assert info.site == "dramabox"
        assert info.media_id == "102"
        assert info.is_hls is True
        assert len(info.variants) == 1
        assert info.variants[0].url == "https://cdn.dramabox.com/ep2.m3u8"


def test_reelshort_parse_url():
    url = "https://www.reelshort.com/episodes/episode-2-don-t-miss-me-when-i-m-gone-6825b4807cc7bf22e3085e15-aqlsax1t61"
    parsed = reelshort.parse_reelshort_url(url)
    assert parsed["serial_number"] == 2
    assert parsed["slug"] == "don-t-miss-me-when-i-m-gone"
    assert parsed["book_id"] == "6825b4807cc7bf22e3085e15"
    assert parsed["chapter_id"] == "aqlsax1t61"


@pytest.mark.asyncio
async def test_reelshort_api():
    mock_data = {
        "data": {
            "episodeList": [
                {"episodeId": 201, "title": "ReelShort Ep 1", "free": True, "playUrl": "https://cdn.reelshort.com/ep1.mp4"}
            ]
        }
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_data

    with patch("app.extractors.reelshort.get", new=AsyncMock(return_value=mock_resp)):
        info = await reelshort._api("series888", "https://reelshort.com/drama/series888", {})
        assert info.site == "reelshort"
        assert info.media_id == "201"
        assert info.is_hls is False
        assert len(info.variants) == 1
        assert info.variants[0].url == "https://cdn.reelshort.com/ep1.mp4"


@pytest.mark.asyncio
async def test_shortmax_api():
    mock_data = {
        "data": {
            "episodeList": [
                {"episodeId": 301, "title": "ShortMax Ep 1", "isFree": True, "videoUrl": "https://cdn.shortmax.com/ep1.m3u8"}
            ]
        }
    }

    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_data

    with patch("app.extractors.shortmax.get", new=AsyncMock(return_value=mock_resp)):
        info = await shortmax._api("drama777", "https://shortmax.com/drama/drama777", {})
        assert info.site == "shortmax"
        assert info.media_id == "301"
        assert info.is_hls is True
        assert len(info.variants) == 1
        assert info.variants[0].url == "https://cdn.shortmax.com/ep1.m3u8"
