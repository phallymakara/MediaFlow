"""Tests for DownloaderPage formatting, helpers, and episode selection logic."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from app.core.media import MediaEpisode, MediaInfo
from app.database.models import DownloadStatus
from app.gui.downloader_page import format_bytes, format_eta, format_speed


def test_format_bytes() -> None:
    """Verify human-readable file size formatting."""
    assert format_bytes(0) == "--"
    assert format_bytes(-5) == "--"
    assert format_bytes(512) == "512.0 B"
    assert format_bytes(1024 * 25) == "25.0 KB"
    assert format_bytes(1024 * 1024 * 142) == "142.0 MB"
    assert format_bytes(int(1024 * 1024 * 1024 * 2.5)) == "2.5 GB"


def test_format_speed() -> None:
    """Verify download speed string formatting."""
    assert format_speed(0.0) == "--"
    assert format_speed(-10.0) == "--"
    assert format_speed(1024 * 80) == "80.0 KB/s"
    assert format_speed(1024 * 1024 * 8.6) == "8.6 MB/s"


def test_format_eta() -> None:
    """Verify remaining duration ETA formatting."""
    assert format_eta(None) == "--"
    assert format_eta(0) == "--"
    assert format_eta(24) == "24s"
    assert format_eta(75) == "1m 15s"
    assert format_eta(3665) == "1h 01m"


def test_media_episode_selection_logic() -> None:
    """Verify episode data structure and filtering for drama series."""
    episodes = [
        MediaEpisode(episode_number=1, title="Episode 1", url="https://example.com/ep1"),
        MediaEpisode(episode_number=2, title="Episode 2", url="https://example.com/ep2"),
        MediaEpisode(episode_number=3, title="Episode 3", url="https://example.com/ep3"),
    ]

    media_info = MediaInfo(
        url="https://example.com/series",
        title="Drama Series",
        platform="dramabox",
        episodes=episodes,
        is_playlist=True,
    )

    assert len(media_info.episodes) == 3
    assert media_info.is_playlist is True

    # Filter selection simulation
    selected = [ep for ep in media_info.episodes if ep.episode_number in (1, 3)]
    assert len(selected) == 2
    assert selected[0].episode_number == 1
    assert selected[1].episode_number == 3
