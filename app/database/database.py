"""SQLite database manager."""

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional, Union

from app.config import get_config

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages SQLite connection lifecycle, WAL configuration, and schema migrations."""

    def __init__(self, db_path: Optional[Union[Path, str]] = None) -> None:
        """Initialize DatabaseManager with database file path or in-memory identifier."""
        if db_path is not None:
            self.db_path: Union[Path, str] = db_path
        else:
            self.db_path = get_config().db_path

        self._lock = threading.Lock()
        self._shared_memory_conn: Optional[sqlite3.Connection] = None

        if self.db_path == ":memory:":
            self._shared_memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._shared_memory_conn.row_factory = sqlite3.Row
        elif isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.init_db()

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Provide a transactional SQLite connection configured with Row factory and pragmas.

        Yields:
            An active sqlite3.Connection instance with row_factory set to sqlite3.Row.
        """
        with self._lock:
            if self._shared_memory_conn is not None:
                try:
                    yield self._shared_memory_conn
                    self._shared_memory_conn.commit()
                except Exception:
                    self._shared_memory_conn.rollback()
                    raise
                return

            conn = sqlite3.connect(
                str(self.db_path),
                timeout=10.0,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA foreign_keys = ON;")
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA busy_timeout = 5000;")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def init_db(self) -> None:
        """Initialize database tables and indexes if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Downloads history and queue table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT UNIQUE NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    thumbnail_url TEXT,
                    output_path TEXT NOT NULL,
                    file_format TEXT,
                    quality TEXT,
                    status TEXT NOT NULL,
                    downloaded_bytes INTEGER DEFAULT 0,
                    total_bytes INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            # Indexes for efficient queries
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_downloads_task_id ON downloads(task_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_downloads_created_at ON downloads(created_at);")

            # Key-value settings table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

        logger.debug("Database initialized at %s", self.db_path)

