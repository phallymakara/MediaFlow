"""Unit tests for BrowserSnifferService and sequential episode probing."""

from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from app.core.media import MediaEpisode
from app.extractors.drama_base import BaseDramaExtractor
from app.services.browser_sniffer import BrowserSnifferService


def test_browser_sniffer_is_available() -> None:
    """Verify is_available returns a valid boolean."""
    assert isinstance(BrowserSnifferService.is_available(), bool)


def test_browser_sniffer_blocks_unsafe_urls() -> None:
    """Verify SSRF and loopback targets are rejected cleanly."""
    assert BrowserSnifferService.sniff_media_streams("http://localhost:8080") == []
    assert BrowserSnifferService.sniff_media_streams("http://127.0.0.1/admin") == []
    assert BrowserSnifferService.sniff_media_streams("ftp://example.com/stream.mp4") == []
    assert BrowserSnifferService.sniff_media_streams("") == []


def test_browser_sniffer_mocked_execution() -> None:
    """Verify stream detection and DOM inspection with mocked Playwright."""
    with patch("playwright.sync_api.sync_playwright") as mock_pw:
        mock_instance = MagicMock()
        mock_pw.return_value.__enter__.return_value = mock_instance

        mock_browser = MagicMock()
        mock_instance.chromium.launch.return_value = mock_browser

        mock_context = MagicMock()
        mock_browser.new_context.return_value = mock_context

        mock_page = MagicMock()
        mock_context.new_page.return_value = mock_page

        # Mock DOM video element
        mock_video_el = MagicMock()
        mock_video_el.get_attribute.return_value = "https://cdn.example.com/video/master.m3u8"
        mock_page.query_selector_all.return_value = [mock_video_el]

        # Simulate response callback
        def fake_goto(url, **kwargs):
            # Trigger the registered response callback
            calls = [call for call in mock_page.on.call_args_list if call[0][0] == "response"]
            if calls:
                cb = calls[0][0][1]
                mock_resp = MagicMock()
                mock_resp.url = "https://cdn.example.com/streams/playlist.m3u8"
                mock_resp.headers = {"content-type": "application/vnd.apple.mpegurl"}
                cb(mock_resp)

        mock_page.goto.side_effect = fake_goto

        streams = BrowserSnifferService.sniff_media_streams("https://example.com/watch/drama-1")

        assert "https://cdn.example.com/streams/playlist.m3u8" in streams
        assert "https://cdn.example.com/video/master.m3u8" in streams
        mock_browser.close.assert_called_once()


def test_probe_sequential_cdn_episodes() -> None:
    """Verify probe_sequential_cdn_episodes discovers consecutive episodes."""
    mock_client = MagicMock()

    # Simulate episode 2 and 3 existing, but 4 returning 404
    def fake_head(url, timeout=3.0):
        mock_resp = MagicMock()
        mock_resp.status_code = 200 if ("ep02.m3u8" in url or "ep03.m3u8" in url) else 404
        return mock_resp

    mock_client.head = MagicMock(side_effect=fake_head)

    class DummyDramaExtractor(BaseDramaExtractor):
        @property
        def platform_name(self) -> str:
            return "DummyDrama"

        def can_handle(self, url: str) -> bool:
            return True

    extractor = DummyDramaExtractor(client=mock_client)
    initial_episodes = [
        MediaEpisode(episode_number=1, title="Episode 1", url="https://cdn.example.com/dramas/ep01.m3u8")
    ]

    probed = extractor.probe_sequential_cdn_episodes(
        base_stream_url="https://cdn.example.com/dramas/ep01.m3u8",
        detected_episodes=initial_episodes,
        max_probe=5,
    )

    assert len(probed) == 3
    assert probed[0].episode_number == 1
    assert probed[1].episode_number == 2
    assert probed[1].url == "https://cdn.example.com/dramas/ep02.m3u8"
    assert probed[2].episode_number == 3
    assert probed[2].url == "https://cdn.example.com/dramas/ep03.m3u8"
