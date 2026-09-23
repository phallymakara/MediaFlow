"""Metadata normalization and parsing service."""

import html
import re
from typing import Optional


class MetadataService:
    """Provides common media metadata extraction and normalization helpers."""

    @staticmethod
    def format_bytes(bytes_count: Optional[int]) -> str:
        """Format an integer byte count into a human-readable string.

        Args:
            bytes_count: Raw size in bytes.

        Returns:
            Human-readable size string (e.g. '12.40 MB').
        """
        if bytes_count is None or bytes_count < 0:
            return "0 B"

        if bytes_count < 1024:
            return f"{bytes_count} B"
        elif bytes_count < 1024**2:
            return f"{bytes_count / 1024:.2f} KB"
        elif bytes_count < 1024**3:
            return f"{bytes_count / (1024**2):.2f} MB"
        else:
            return f"{bytes_count / (1024**3):.2f} GB"

    @staticmethod
    def format_duration(seconds: Optional[int]) -> str:
        """Format duration in seconds into MM:SS or HH:MM:SS format.

        Args:
            seconds: Total duration in seconds.

        Returns:
            Formatted time string (e.g. '03:45' or '01:12:30').
        """
        if seconds is None or seconds < 0:
            return "--:--"

        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    @staticmethod
    def format_speed(bytes_per_sec: Optional[float]) -> str:
        """Format transfer speed in bytes per second into human-readable string.

        Args:
            bytes_per_sec: Transfer speed in bytes per second.

        Returns:
            Formatted speed string (e.g. '2.40 MB/s').
        """
        if bytes_per_sec is None or bytes_per_sec <= 0:
            return "0 KB/s"

        if bytes_per_sec < 1024:
            return f"{bytes_per_sec:.0f} B/s"
        elif bytes_per_sec < 1024**2:
            return f"{bytes_per_sec / 1024:.2f} KB/s"
        else:
            return f"{bytes_per_sec / (1024**2):.2f} MB/s"

    @staticmethod
    def clean_title(raw_title: str) -> str:
        """Clean and normalize media title string.

        Decodes HTML entities and normalizes multiple whitespace characters.

        Args:
            raw_title: Raw title string from web page or API.

        Returns:
            Normalized clean title string.
        """
        if not raw_title or not raw_title.strip():
            return "Untitled Media"

        # Decode HTML entities (e.g. &amp; -> &, &quot; -> ")
        title = html.unescape(raw_title)

        # Collapse whitespace and strip leading/trailing spaces
        title = re.sub(r"\s+", " ", title).strip()

        return title or "Untitled Media"

