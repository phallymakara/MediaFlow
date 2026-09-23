"""Data access repositories for downloads and application settings."""

import logging
from datetime import datetime, timezone
from typing import List, Optional

from app.database.database import DatabaseManager
from app.database.models import DownloadRecord, DownloadStatus, SettingRecord

logger = logging.getLogger(__name__)


class DownloadRepository:
    """Repository handling database operations for media downloads."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        """Initialize repository with a DatabaseManager instance."""
        self.db = db_manager

    def add(self, record: DownloadRecord) -> DownloadRecord:
        """Insert a new download record into the database.

        Args:
            record: DownloadRecord instance to insert.

        Returns:
            The inserted DownloadRecord updated with its database row id.
        """
        query = """
            INSERT INTO downloads (
                task_id, url, title, platform, thumbnail_url, output_path,
                file_format, quality, status, downloaded_bytes, total_bytes,
                error_message, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        params = (
            record.task_id,
            record.url,
            record.title,
            record.platform,
            record.thumbnail_url,
            record.output_path,
            record.file_format,
            record.quality,
            record.status.value,
            record.downloaded_bytes,
            record.total_bytes,
            record.error_message,
            record.created_at,
            record.updated_at,
        )

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            record.id = cursor.lastrowid

        logger.debug("Inserted download task %s with row id %s", record.task_id, record.id)
        return record

    def update_progress(
        self,
        task_id: str,
        downloaded_bytes: int,
        total_bytes: int,
    ) -> bool:
        """Update downloaded and total byte counts for an active task.

        Args:
            task_id: Unique task identifier.
            downloaded_bytes: Current downloaded byte count.
            total_bytes: Total file size in bytes.

        Returns:
            True if a row was updated, False otherwise.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        query = """
            UPDATE downloads
            SET downloaded_bytes = ?, total_bytes = ?, updated_at = ?
            WHERE task_id = ?;
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (downloaded_bytes, total_bytes, now_iso, task_id))
            return cursor.rowcount > 0

    def update_status(
        self,
        task_id: str,
        status: DownloadStatus,
        error_message: Optional[str] = None,
    ) -> bool:
        """Update status and optional error message for a download task.

        Args:
            task_id: Unique task identifier.
            status: New DownloadStatus value.
            error_message: Optional error message string.

        Returns:
            True if a row was updated, False otherwise.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        query = """
            UPDATE downloads
            SET status = ?, error_message = ?, updated_at = ?
            WHERE task_id = ?;
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (status.value, error_message, now_iso, task_id))
            return cursor.rowcount > 0

    def get_by_id(self, task_id: str) -> Optional[DownloadRecord]:
        """Retrieve a download record by its task identifier.

        Args:
            task_id: Unique task identifier.

        Returns:
            Matching DownloadRecord, or None if not found.
        """
        query = "SELECT * FROM downloads WHERE task_id = ?;"
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (task_id,))
            row = cursor.fetchone()
            if row:
                return DownloadRecord.from_row(row)
        return None

    def get_all(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[DownloadStatus] = None,
        search: Optional[str] = None,
    ) -> List[DownloadRecord]:
        """Retrieve download records with optional status filter and title search.

        Args:
            limit: Maximum number of rows to return.
            offset: Pagination offset.
            status: Optional status to filter by.
            search: Optional keyword to match against title or URL.

        Returns:
            List of matching DownloadRecord instances.
        """
        query_parts = ["SELECT * FROM downloads WHERE 1=1"]
        params: list = []

        if status:
            query_parts.append("AND status = ?")
            params.append(status.value)

        if search and search.strip():
            query_parts.append("AND (title LIKE ? OR url LIKE ?)")
            pattern = f"%{search.strip()}%"
            params.extend([pattern, pattern])

        query_parts.append("ORDER BY id DESC LIMIT ? OFFSET ?;")
        params.extend([limit, offset])

        full_query = " ".join(query_parts)
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(full_query, tuple(params))
            rows = cursor.fetchall()
            return [DownloadRecord.from_row(row) for row in rows]

    def delete(self, task_id: str) -> bool:
        """Delete a download record by task identifier.

        Args:
            task_id: Unique task identifier.

        Returns:
            True if row was deleted, False otherwise.
        """
        query = "DELETE FROM downloads WHERE task_id = ?;"
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (task_id,))
            return cursor.rowcount > 0

    def clear_history(self, status_filter: Optional[DownloadStatus] = None) -> int:
        """Delete completed or failed history entries.

        Args:
            status_filter: Specific status to clear. If None, clears completed, failed, and cancelled.

        Returns:
            Count of rows deleted.
        """
        if status_filter:
            query = "DELETE FROM downloads WHERE status = ?;"
            params = (status_filter.value,)
        else:
            query = "DELETE FROM downloads WHERE status IN (?, ?, ?);"
            params = (
                DownloadStatus.COMPLETED.value,
                DownloadStatus.FAILED.value,
                DownloadStatus.CANCELLED.value,
            )

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.rowcount


class SettingsRepository:
    """Repository handling key-value configuration settings in the database."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        """Initialize settings repository with DatabaseManager."""
        self.db = db_manager

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Retrieve setting value by key.

        Args:
            key: Configuration key.
            default: Default value returned if key does not exist.

        Returns:
            Setting value string or default.
        """
        query = "SELECT value FROM settings WHERE key = ?;"
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (key,))
            row = cursor.fetchone()
            if row:
                return str(row["value"])
        return default

    def set(self, key: str, value: str) -> bool:
        """Insert or update a configuration setting.

        Args:
            key: Configuration key.
            value: Configuration value string.

        Returns:
            True on successful persistence.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        query = """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at;
        """
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (key, value, now_iso))
            return cursor.rowcount > 0
