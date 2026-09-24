"""Unit tests for AsyncDownloaderService."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.async_downloader import AsyncDownloaderService, AsyncDownloadCancelled


def test_async_downloader_rejects_unsafe_urls(tmp_path: Path) -> None:
    """Verify SSRF protection rejects loopback and invalid URLs."""
    downloader = AsyncDownloaderService()
    dest = tmp_path / "test.mp4"

    with pytest.raises(ValueError):
        downloader.download("http://localhost:8000/stream.mp4", dest)

    with pytest.raises(ValueError):
        downloader.download("http://127.0.0.1/video.mp4", dest)


@pytest.mark.asyncio
async def test_parse_hls_playlist_master_and_media() -> None:
    """Verify parsing handles master playlists with bandwidth selection and media segments."""
    downloader = AsyncDownloaderService()

    master_content = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360
low.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2400000,RESOLUTION=1280x720
high.m3u8
"""

    media_content = """#EXTM3U
#EXT-X-TARGETDURATION:10
#EXTINF:9.009,
segment_0.ts
#EXTINF:9.009,
segment_1.ts
"""

    mock_session = MagicMock()

    class MockResp:
        def __init__(self, text_val):
            self._text = text_val
            self.status = 200

        async def text(self):
            return self._text

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    def fake_get(url):
        if "master.m3u8" in url:
            return MockResp(master_content)
        return MockResp(media_content)

    mock_session.get.side_effect = fake_get

    segments = await downloader._parse_hls_playlist(mock_session, "https://cdn.example.com/master.m3u8")

    assert len(segments) == 2
    assert segments[0] == "https://cdn.example.com/segment_0.ts"
    assert segments[1] == "https://cdn.example.com/segment_1.ts"


def test_async_downloader_direct_cancellation(tmp_path: Path) -> None:
    """Verify cancellation flag triggers AsyncDownloadCancelled."""
    downloader = AsyncDownloaderService()
    dest = tmp_path / "cancelled.mp4"

    with patch.object(downloader, "_download_async", side_effect=AsyncDownloadCancelled("Cancelled")):
        with pytest.raises(AsyncDownloadCancelled):
            downloader.download(
                url="https://example.com/media.mp4",
                dest_path=dest,
                is_cancelled_callback=lambda: True,
            )
