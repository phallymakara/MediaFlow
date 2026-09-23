"""History and library management page for MediaFlow GUI."""

from datetime import datetime
import logging
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.database.database import DatabaseManager
from app.database.models import DownloadRecord, DownloadStatus
from app.database.repository import DownloadRepository
from app.gui.assets import create_vector_icon
from app.gui.downloader_page import format_bytes
from app.gui.styles import COLORS

logger = logging.getLogger(__name__)

PLATFORM_OPTIONS = [
    "All Platforms",
    "YouTube",
    "TikTok",
    "Instagram",
    "Facebook",
    "X",
    "Reddit",
    "Vimeo",
    "DramaBox",
    "NetShort",
    "FlickReels",
    "StardustTV",
    "GoodShort",
    "DramaWave",
    "FreeReels",
    "Direct",
]

STATUS_OPTIONS = [
    "All Status",
    "Completed",
    "Failed",
    "Cancelled",
    "Queued",
    "Downloading",
]


def format_history_date(iso_timestamp: Optional[str]) -> str:
    """Format an ISO-8601 timestamp string into human-readable YYYY-MM-DD HH:MM format."""
    if not iso_timestamp:
        return "--"
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        # Fallback to prefix if parsing fails
        return iso_timestamp[:16].replace("T", " ")


def filter_records(
    records: List[DownloadRecord],
    search: Optional[str] = None,
    platform: Optional[str] = None,
    status: Optional[str] = None,
) -> List[DownloadRecord]:
    """Filter records based on keyword, platform, and status.

    Args:
        records: List of DownloadRecord items.
        search: Optional case-insensitive search string matching title or URL.
        platform: Optional platform filter (e.g. 'YouTube' or 'All Platforms').
        status: Optional status filter (e.g. 'Completed' or 'All Status').

    Returns:
        Filtered list of DownloadRecord items.
    """
    filtered = records

    if search and search.strip():
        q = search.strip().lower()
        filtered = [r for r in filtered if q in (r.title or "").lower() or q in (r.url or "").lower()]

    if platform and platform != "All Platforms":
        p = platform.lower()
        filtered = [r for r in filtered if (r.platform or "").lower() == p]

    if status and status != "All Status":
        s = status.lower()
        filtered = [r for r in filtered if r.status.value.lower() == s]

    return filtered


class HistoryPage(QWidget):
    """Download history and library page connected to SQLite repository."""

    def __init__(
        self,
        repository: Optional[DownloadRepository] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize history page.

        Args:
            repository: DownloadRepository instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.repo = repository or DownloadRepository(db_manager=DatabaseManager())

        self._all_records: List[DownloadRecord] = []
        self._displayed_records: List[DownloadRecord] = []

        self._init_ui()
        self.reload_history()

    def _init_ui(self) -> None:
        """Construct the History page layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # 1. Top Search & Filter Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._search_input = QLineEdit(self)
        self._search_input.setPlaceholderText("Search title or URL...")
        self._search_input.textChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._search_input, 1)

        self._platform_combo = QComboBox(self)
        self._platform_combo.addItems(PLATFORM_OPTIONS)
        self._platform_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._platform_combo)

        self._status_combo = QComboBox(self)
        self._status_combo.addItems(STATUS_OPTIONS)
        self._status_combo.currentIndexChanged.connect(self._on_filter_changed)
        toolbar.addWidget(self._status_combo)

        refresh_btn = QPushButton("Refresh", self)
        refresh_btn.setIcon(create_vector_icon("retry", size=14))
        refresh_btn.clicked.connect(self.reload_history)
        toolbar.addWidget(refresh_btn)

        clear_btn = QPushButton("Clear History", self)
        clear_btn.setObjectName("dangerButton")
        clear_btn.clicked.connect(self._on_clear_history_clicked)
        toolbar.addWidget(clear_btn)

        layout.addLayout(toolbar)

        # 2. History Table (QTableWidget)
        self._table = QTableWidget(self)
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "Title", "Platform", "Format", "Size", "Date", "Actions"
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Title stretches
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(5, 190)

        layout.addWidget(self._table, 1)

        # 3. Bottom Summary Strip
        bottom_strip = QHBoxLayout()
        bottom_strip.setContentsMargins(4, 4, 4, 4)

        self._summary_label = QLabel("Total Records: 0 files (0 MB)", self)
        self._summary_label.setObjectName("captionText")
        bottom_strip.addWidget(self._summary_label)

        bottom_strip.addStretch()

        self._reset_filter_btn = QPushButton("Reset Filters", self)
        self._reset_filter_btn.setObjectName("rowActionButton")
        self._reset_filter_btn.hide()
        self._reset_filter_btn.clicked.connect(self._reset_filters)
        bottom_strip.addWidget(self._reset_filter_btn)

        layout.addLayout(bottom_strip)

    def reload_history(self) -> None:
        """Fetch all records from SQLite and re-apply active filters."""
        try:
            self._all_records = self.repo.get_all(limit=500)
            self._apply_filters()
        except Exception as exc:
            logger.error("Failed querying download history: %s", exc)

    def _on_filter_changed(self) -> None:
        """Re-filter records on input changes."""
        self._apply_filters()

    def _reset_filters(self) -> None:
        """Reset search and dropdown filters back to defaults."""
        self._search_input.clear()
        self._platform_combo.setCurrentIndex(0)
        self._status_combo.setCurrentIndex(0)
        self._apply_filters()

    def _apply_filters(self) -> None:
        """Filter records and populate table rows."""
        search_text = self._search_input.text().strip()
        selected_platform = self._platform_combo.currentText()
        selected_status = self._status_combo.currentText()

        has_filters = bool(search_text or selected_platform != "All Platforms" or selected_status != "All Status")
        self._reset_filter_btn.setVisible(has_filters)

        self._displayed_records = filter_records(
            records=self._all_records,
            search=search_text,
            platform=selected_platform,
            status=selected_status,
        )

        self._populate_table()
        self._update_summary()

    def _populate_table(self) -> None:
        """Render displayed records into table rows."""
        self._table.setRowCount(0)

        for row, record in enumerate(self._displayed_records):
            self._table.insertRow(row)
            self._table.setRowHeight(row, 44)

            # 0: Title (Icon + Text)
            title_widget = QWidget()
            t_layout = QHBoxLayout(title_widget)
            t_layout.setContentsMargins(8, 0, 8, 0)
            t_layout.setSpacing(8)

            icon_label = QLabel(title_widget)
            icon_label.setPixmap(create_vector_icon("history", size=15).pixmap(15, 15))
            t_layout.addWidget(icon_label)

            title_label = QLabel(record.title or "Untitled Media", title_widget)
            tooltip_text = f"Title: {record.title}\nURL: {record.url}\nFile: {record.output_path}"
            title_label.setToolTip(tooltip_text)
            t_layout.addWidget(title_label, 1)

            self._table.setCellWidget(row, 0, title_widget)

            # 1: Platform
            platform_label = QLabel((record.platform or "generic").title())
            platform_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setCellWidget(row, 1, platform_label)

            # 2: Format / Quality
            fmt_str = record.file_format or "mp4"
            if record.quality:
                fmt_str = f"{fmt_str.upper()} - {record.quality}"
            else:
                fmt_str = fmt_str.upper()
            fmt_label = QLabel(fmt_str)
            fmt_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setCellWidget(row, 2, fmt_label)

            # 3: Size
            bytes_val = record.total_bytes or record.downloaded_bytes
            size_label = QLabel(format_bytes(bytes_val))
            size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            size_label.setObjectName("captionText")
            self._table.setCellWidget(row, 3, size_label)

            # 4: Date
            date_label = QLabel(format_history_date(record.created_at))
            date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            date_label.setObjectName("captionText")
            self._table.setCellWidget(row, 4, date_label)

            # 5: Actions (Open Folder, Play, Delete)
            action_widget = QWidget()
            a_layout = QHBoxLayout(action_widget)
            a_layout.setContentsMargins(4, 0, 4, 0)
            a_layout.setSpacing(4)

            open_btn = QPushButton("Folder", action_widget)
            open_btn.setObjectName("rowActionButton")
            open_btn.setToolTip("Open folder in File Explorer")
            open_btn.clicked.connect(lambda checked=False, p=record.output_path: self._open_folder(p))
            a_layout.addWidget(open_btn)

            play_btn = QPushButton("Play", action_widget)
            play_btn.setObjectName("rowActionButton")
            play_btn.setToolTip("Play file with default player")
            play_btn.clicked.connect(lambda checked=False, p=record.output_path: self._play_file(p))
            a_layout.addWidget(play_btn)

            del_btn = QPushButton("Delete", action_widget)
            del_btn.setObjectName("rowActionButton")
            del_btn.setToolTip("Delete history record")
            del_btn.clicked.connect(lambda checked=False, tid=record.task_id: self._delete_record(tid))
            a_layout.addWidget(del_btn)

            self._table.setCellWidget(row, 5, action_widget)

    def _open_folder(self, file_path: str) -> None:
        """Open parent directory in Windows File Explorer."""
        p = Path(file_path).resolve()
        folder = p.parent if p.is_file() else p
        if folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _play_file(self, file_path: str) -> None:
        """Launch downloaded media in the system default media player."""
        p = Path(file_path).resolve()
        if p.exists() and p.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _delete_record(self, task_id: str) -> None:
        """Delete a record from the database and refresh the table."""
        try:
            self.repo.delete(task_id)
            self._all_records = [r for r in self._all_records if r.task_id != task_id]
            self._apply_filters()
        except Exception as exc:
            logger.error("Failed deleting record %s: %s", task_id, exc)

    def _on_clear_history_clicked(self) -> None:
        """Prompt confirmation and purge history records."""
        if not self._all_records:
            return

        reply = QMessageBox.question(
            self,
            "Clear Download History",
            "Are you sure you want to clear your download history?\n(Downloaded files on disk will not be deleted)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.repo.clear_history()
                self._all_records.clear()
                self._apply_filters()
            except Exception as exc:
                logger.error("Failed clearing history: %s", exc)

    def _update_summary(self) -> None:
        """Update bottom summary count and total disk usage."""
        count = len(self._displayed_records)
        total_bytes = sum(r.total_bytes or r.downloaded_bytes for r in self._displayed_records)
        self._summary_label.setText(f"Total Records: {count} files ({format_bytes(total_bytes)})")
