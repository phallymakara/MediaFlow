"""Normalized media data models."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MediaFormat:
    """Format description for a downloadable stream."""

    format_id: str
    extension: str
    resolution: Optional[str] = None
    filesize_approx: Optional[int] = None
    note: Optional[str] = None
    has_video: bool = True
    has_audio: bool = True


@dataclass
class MediaEpisode:
    """Information for a single episode in a series or drama."""

    episode_number: int
    title: str
    url: str
    duration_seconds: Optional[int] = None


@dataclass
class MediaInfo:
    """Standardized metadata extracted from any supported platform."""

    url: str
    title: str
    platform: str
    thumbnail_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    formats: List[MediaFormat] = field(default_factory=list)
    episodes: List[MediaEpisode] = field(default_factory=list)
    is_playlist: bool = False

