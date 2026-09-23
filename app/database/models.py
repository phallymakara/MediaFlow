"""Database models for media downloads and application settings."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class DownloadStatus(str, Enum):
    """Enumeration of possible lifecycle states for a download task."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DownloadRecord:
    """Represents a media download task and history entry."""

    task_id: str
    url: str
    title: str
    platform: str
    output_path: str
    status: DownloadStatus = DownloadStatus.QUEUED
    thumbnail_url: Optional[str] = None
    file_format: Optional[str] = None
    quality: Optional[str] = None
    downloaded_bytes: int = 0
    total_bytes: int = 0
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    id: Optional[int] = None

    def __post_init__(self) -> None:
        """Ensure timestamps and status types are normalized."""
        now_iso = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now_iso
        if not self.updated_at:
            self.updated_at = now_iso
        if isinstance(self.status, str) and not isinstance(self.status, DownloadStatus):
            self.status = DownloadStatus(self.status)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "DownloadRecord":
        """Instantiate a DownloadRecord from an SQLite row."""
        return cls(
            id=row["id"],
            task_id=row["task_id"],
            url=row["url"],
            title=row["title"],
            platform=row["platform"],
            thumbnail_url=row["thumbnail_url"],
            output_path=row["output_path"],
            file_format=row["file_format"],
            quality=row["quality"],
            status=DownloadStatus(row["status"]),
            downloaded_bytes=row["downloaded_bytes"],
            total_bytes=row["total_bytes"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class SettingRecord:
    """Represents an application key-value configuration preference."""

    key: str
    value: str
    updated_at: Optional[str] = None

    def __post_init__(self) -> None:
        """Assign default timestamp if absent."""
        if not self.updated_at:
            self.updated_at = datetime.now(timezone.utc).isoformat()

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "SettingRecord":
        """Instantiate a SettingRecord from an SQLite row."""
        return cls(
            key=row["key"],
            value=row["value"],
            updated_at=row["updated_at"],
        )

