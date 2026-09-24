"""History and library management page for MediaFlow GUI."""

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
import re
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
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.database.database import DatabaseManager
from app.database.models import DownloadRecord, DownloadStatus
from app.database.repository import DownloadRepository
from app.gui.assets import create_vector_icon
from app.gui.downloader_page import format_bytes
from app.gui.styles import COLORS
from app.gui.widgets.status_badge import StatusBadge

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


def extract_base_title(title: str) -> str:
    """Extract clean parent title from multi-episode format like 'Title - Ep 01'."""
    if not title:
        return "Untitled Media"
    parts = re.split(r"\s*[-–—]\s*Ep(?:isode|\.)?\s*\d+", title, flags=re.IGNORECASE)
    if parts and parts[0].strip():
        return parts[0].strip()
    return title.strip()


@dataclass
class HistoryGroup:
    """Grouped download session aggregating multi-episode series or single downloads."""

    base_title: str
    date_key: str
    formatted_date: str
    platform: str
    records: List[DownloadRecord]

    @property
    def total_count(self) -> int:
        """Total count of items in this group."""
        return len(self.records)

    @property
    def completed_count(self) -> int:
        """Count of completed items in this group."""
        return sum(1 for r in self.records if r.status == DownloadStatus.COMPLETED)

    @property
    def failed_count(self) -> int:
        """Count of failed items in this group."""
        return sum(1 for r in self.records if r.status == DownloadStatus.FAILED)

    @property
    def total_bytes(self) -> int:
        """Total size in bytes across all items in this group."""
        return sum(r.total_bytes or r.downloaded_bytes for r in self.records)

    @property
    def folder_path(self) -> Optional[str]:
        """Parent folder of the first valid record in this group."""
        for r in self.records:
            if r.output_path:
                return r.output_path
        return None


def group_records(records: List[DownloadRecord]) -> List[HistoryGroup]:
    """Group flat download records into logical download sessions by title and date."""
    groups_dict: Dict[tuple, List[DownloadRecord]] = {}

    for r in records:
        base = extract_base_title(r.title or "Untitled Media")
        date_key = r.created_at[:16] if r.created_at else ""
        key = (base, date_key, (r.platform or "generic").lower())
        groups_dict.setdefault(key, []).append(r)

    result: List[HistoryGroup] = []
    for (base, date_key, _platform_key), recs in groups_dict.items():
        sample_created = recs[0].created_at if recs else ""
        formatted_date = format_history_date(sample_created)
        platform_name = (recs[0].platform or "Generic").title() if recs else "Generic"

        result.append(
            HistoryGroup(
                base_title=base,
                date_key=date_key,
                formatted_date=formatted_date,
                platform=platform_name,
                records=recs,
            )
        )
    return result


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


def filter_groups(
    groups: List[HistoryGroup],
    search: Optional[str] = None,
    platform: Optional[str] = None,
    status: Optional[str] = None,
) -> List[HistoryGroup]:
    """Filter groups based on keyword, platform, and record statuses."""
    filtered = groups

    if search and search.strip():
        q = search.strip().lower()
        filtered = [
            g
            for g in filtered
            if q in g.base_title.lower()
            or any(q in (r.title or "").lower() or q in (r.url or "").lower() for r in g.records)
        ]

    if platform and platform != "All Platforms":
        p = platform.lower()
        filtered = [g for g in filtered if g.platform.lower() == p]

    if status and status != "All Status":
        s = status.lower()
        filtered = [
            g for g in filtered if any(r.status.value.lower() == s for r in g.records)
        ]

    return filtered


class HistoryPage(QWidget):
    """Download history and library page supporting grouped views and drill-down details."""

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
        self._all_groups: List[HistoryGroup] = []
        self._displayed_groups: List[HistoryGroup] = []
        self._active_group: Optional[HistoryGroup] = None

        self._history_icon = create_vector_icon("history", size=15)
        self._folder_icon = create_vector_icon("folder", size=14)

        self._init_ui()
        self.reload_history()

    def _init_ui(self) -> None:
        """Construct the stacked History page layout (Grouped overview & Detail view)."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self._view_stack = QStackedWidget(self)
        main_layout.addWidget(self._view_stack)

        # ---------------- Page 0: Grouped History Overview ----------------
        self._groups_view = QWidget(self)
        groups_layout = QVBoxLayout(self._groups_view)
        groups_layout.setContentsMargins(24, 20, 24, 20)
        groups_layout.setSpacing(14)

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

        groups_layout.addLayout(toolbar)

        # 2. Main Groups Table (QTableWidget)
        self._table = QTableWidget(self)
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "Title", "Platform", "Videos", "Size", "Date & Time", "Actions"
        ])
        header_tooltips = {
            0: "Media title and series name (click to view all videos)",
            1: "Platform source",
            2: "Number of videos and status summary",
            3: "Total file size across all episodes",
            4: "Download date and time",
            5: "Actions (View all videos, Open folder, Delete series)",
        }
        for col, tip in header_tooltips.items():
            item = self._table.horizontalHeaderItem(col)
            if item:
                item.setToolTip(tip)

        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(False)
        self._table.setShowGrid(False)
        self._table.cellDoubleClicked.connect(self._on_group_cell_double_clicked)
        self._table.cellClicked.connect(self._on_group_cell_clicked)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Title stretches
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(4, 140)  # Date & Time column
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(5, 190)

        groups_layout.addWidget(self._table, 1)

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

        groups_layout.addLayout(bottom_strip)

        self._view_stack.addWidget(self._groups_view)

        # ---------------- Page 1: Detail Drill-Down View ----------------
        self._detail_view = QWidget(self)
        detail_layout = QVBoxLayout(self._detail_view)
        detail_layout.setContentsMargins(24, 20, 24, 20)
        detail_layout.setSpacing(12)

        # Header Bar with Back button and Title
        detail_header = QHBoxLayout()
        detail_header.setSpacing(12)

        back_btn = QPushButton("Back to History", self._detail_view)
        back_btn.setIcon(create_vector_icon("back", size=14))
        back_btn.clicked.connect(self._navigate_back_to_groups)
        detail_header.addWidget(back_btn)

        self._detail_title_label = QLabel("Download Details", self._detail_view)
        self._detail_title_label.setObjectName("pageTitle")
        self._detail_title_label.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {COLORS.text_primary};")
        detail_header.addWidget(self._detail_title_label, 1)

        self._detail_open_folder_btn = QPushButton("Open Series Folder", self._detail_view)
        self._detail_open_folder_btn.setIcon(self._folder_icon)
        self._detail_open_folder_btn.clicked.connect(self._open_active_group_folder)
        detail_header.addWidget(self._detail_open_folder_btn)

        detail_layout.addLayout(detail_header)

        # Clean stats strip without bulky container frames
        stats_layout = QHBoxLayout()
        stats_layout.setContentsMargins(2, 0, 2, 0)
        stats_layout.setSpacing(18)

        self._stat_total = QLabel("Total Videos: 0", self._detail_view)
        self._stat_total.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLORS.text_primary};")
        stats_layout.addWidget(self._stat_total)

        self._stat_completed = QLabel("Downloaded: 0", self._detail_view)
        self._stat_completed.setStyleSheet("font-size: 13px; font-weight: 600; color: #86efac;")
        stats_layout.addWidget(self._stat_completed)

        self._stat_failed = QLabel("Failed: 0", self._detail_view)
        self._stat_failed.setStyleSheet("font-size: 13px; font-weight: 600; color: #fca5a5;")
        stats_layout.addWidget(self._stat_failed)

        self._stat_size = QLabel("Total Size: 0 MB", self._detail_view)
        self._stat_size.setStyleSheet(f"font-size: 13px; color: {COLORS.text_secondary};")
        stats_layout.addWidget(self._stat_size)

        self._stat_datetime = QLabel("Date & Time: --", self._detail_view)
        self._stat_datetime.setStyleSheet(f"font-size: 13px; color: {COLORS.text_secondary};")
        stats_layout.addWidget(self._stat_datetime)

        stats_layout.addStretch()
        detail_layout.addLayout(stats_layout)

        # Detail Table for individual episodes/files
        self._detail_table = QTableWidget(self._detail_view)
        self._detail_table.setColumnCount(7)
        self._detail_table.setHorizontalHeaderLabels([
            "Episode / Title", "Platform", "Format", "Size", "Status", "Date & Time", "Actions"
        ])
        self._detail_table.verticalHeader().setVisible(False)
        self._detail_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._detail_table.setAlternatingRowColors(False)
        self._detail_table.setShowGrid(False)
        self._detail_table.cellDoubleClicked.connect(self._on_detail_cell_double_clicked)

        d_header = self._detail_table.horizontalHeader()
        d_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        d_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        d_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        d_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        d_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        d_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._detail_table.setColumnWidth(5, 140)
        d_header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self._detail_table.setColumnWidth(6, 135)

        detail_layout.addWidget(self._detail_table, 1)

        self._view_stack.addWidget(self._detail_view)

    def reload_history(self) -> None:
        """Fetch all records from SQLite, re-group, and update the active view."""
        try:
            self._all_records = self.repo.get_all(limit=500)
            self._all_groups = group_records(self._all_records)
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
        """Filter groups and populate table rows."""
        search_text = self._search_input.text().strip()
        selected_platform = self._platform_combo.currentText()
        selected_status = self._status_combo.currentText()

        has_filters = bool(search_text or selected_platform != "All Platforms" or selected_status != "All Status")
        self._reset_filter_btn.setVisible(has_filters)

        self._displayed_groups = filter_groups(
            groups=self._all_groups,
            search=search_text,
            platform=selected_platform,
            status=selected_status,
        )

        self._populate_table()
        self._update_summary()

    def _populate_table(self) -> None:
        """Render displayed groups into the main overview table with high performance."""
        self._table.setUpdatesEnabled(False)
        self._table.blockSignals(True)
        try:
            total_rows = len(self._displayed_groups)
            self._table.setRowCount(total_rows)

            for row, group in enumerate(self._displayed_groups):
                self._table.setRowHeight(row, 44)

                # 0: Title (Group Base Title)
                count_suffix = f" ({group.total_count} videos)" if group.total_count > 1 else ""
                title_item = QTableWidgetItem(self._history_icon, f"{group.base_title}{count_suffix}")
                title_item.setToolTip(f"Title: {group.base_title}\nTotal Videos: {group.total_count}\nClick to view all videos")
                self._table.setItem(row, 0, title_item)

                # 1: Platform
                platform_item = QTableWidgetItem(group.platform)
                platform_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(row, 1, platform_item)

                # 2: Videos (Count & Status breakdown)
                if group.total_count > 1:
                    status_text = f"{group.total_count} items ({group.completed_count} completed)"
                else:
                    status_text = "1 item"
                videos_item = QTableWidgetItem(status_text)
                videos_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(row, 2, videos_item)

                # 3: Size
                size_item = QTableWidgetItem(format_bytes(group.total_bytes))
                size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(row, 3, size_item)

                # 4: Date & Time (YYYY-MM-DD HH:MM)
                date_item = QTableWidgetItem(group.formatted_date)
                date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                date_item.setToolTip(f"Session date: {group.formatted_date}")
                self._table.setItem(row, 4, date_item)

                # 5: Actions (View Details, Open Folder, Delete Group)
                action_widget = QWidget()
                a_layout = QHBoxLayout(action_widget)
                a_layout.setContentsMargins(4, 0, 4, 0)
                a_layout.setSpacing(4)

                view_btn = QPushButton("View", action_widget)
                view_btn.setObjectName("rowActionButton")
                view_btn.setToolTip("View all videos inside this download")
                view_btn.clicked.connect(lambda checked=False, g=group: self._show_group_details(g))
                a_layout.addWidget(view_btn)

                open_btn = QPushButton("Folder", action_widget)
                open_btn.setObjectName("rowActionButton")
                open_btn.setToolTip("Open folder in File Explorer")
                folder_p = group.folder_path or ""
                open_btn.clicked.connect(lambda checked=False, p=folder_p: self._open_folder(p))
                a_layout.addWidget(open_btn)

                del_btn = QPushButton("Delete", action_widget)
                del_btn.setObjectName("rowActionButton")
                del_btn.setToolTip("Delete all records in this group")
                del_btn.clicked.connect(lambda checked=False, g=group: self._delete_group(g))
                a_layout.addWidget(del_btn)

                self._table.setCellWidget(row, 5, action_widget)
        finally:
            self._table.blockSignals(False)
            self._table.setUpdatesEnabled(True)

    def _show_group_details(self, group: HistoryGroup) -> None:
        """Switch to detail view displaying each row inside the selected title and date time."""
        self._active_group = group
        self._detail_title_label.setText(group.base_title)

        # Update stats banner
        self._stat_total.setText(f"Total Videos: {group.total_count}")
        self._stat_completed.setText(f"Downloaded: {group.completed_count}")
        self._stat_failed.setText(f"Failed: {group.failed_count}")
        self._stat_size.setText(f"Total Size: {format_bytes(group.total_bytes)}")
        self._stat_datetime.setText(f"Date & Time: {group.formatted_date}")

        # Populate detail table
        self._detail_table.setUpdatesEnabled(False)
        self._detail_table.blockSignals(True)
        try:
            self._detail_table.setRowCount(len(group.records))
            for row, record in enumerate(group.records):
                self._detail_table.setRowHeight(row, 44)

                # 0: Episode Title
                ep_item = QTableWidgetItem(self._history_icon, record.title or "Untitled Media")
                ep_item.setToolTip(f"Title: {record.title}\nURL: {record.url}\nFile: {record.output_path}")
                self._detail_table.setItem(row, 0, ep_item)

                # 1: Platform
                p_item = QTableWidgetItem((record.platform or "generic").title())
                p_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._detail_table.setItem(row, 1, p_item)

                # 2: Format
                fmt_str = record.file_format or "mp4"
                if record.quality:
                    fmt_str = f"{fmt_str.upper()} - {record.quality}"
                else:
                    fmt_str = fmt_str.upper()
                fmt_item = QTableWidgetItem(fmt_str)
                fmt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._detail_table.setItem(row, 2, fmt_item)

                # 3: Size
                b_val = record.total_bytes or record.downloaded_bytes
                size_item = QTableWidgetItem(format_bytes(b_val))
                size_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._detail_table.setItem(row, 3, size_item)

                # 4: Status Badge
                badge = StatusBadge(status=record.status)
                badge_container = QWidget()
                badge_container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                b_layout = QHBoxLayout(badge_container)
                b_layout.setContentsMargins(4, 0, 4, 0)
                b_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                b_layout.addWidget(badge)
                self._detail_table.setCellWidget(row, 4, badge_container)

                # 5: Date & Time
                d_str = format_history_date(record.created_at)
                date_item = QTableWidgetItem(d_str)
                date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._detail_table.setItem(row, 5, date_item)

                # 6: Actions (Folder, Delete)
                action_widget = QWidget()
                a_layout = QHBoxLayout(action_widget)
                a_layout.setContentsMargins(4, 0, 4, 0)
                a_layout.setSpacing(4)

                open_btn = QPushButton("Folder", action_widget)
                open_btn.setObjectName("rowActionButton")
                open_btn.setToolTip("Open folder in File Explorer")
                open_btn.clicked.connect(lambda checked=False, p=record.output_path: self._open_folder(p))
                a_layout.addWidget(open_btn)

                del_btn = QPushButton("Delete", action_widget)
                del_btn.setObjectName("rowActionButton")
                del_btn.setToolTip("Delete this episode record")
                del_btn.clicked.connect(lambda checked=False, tid=record.task_id: self._delete_record(tid))
                a_layout.addWidget(del_btn)

                self._detail_table.setCellWidget(row, 6, action_widget)
        finally:
            self._detail_table.blockSignals(False)
            self._detail_table.setUpdatesEnabled(True)

        self._view_stack.setCurrentIndex(1)

    def _navigate_back_to_groups(self) -> None:
        """Return from drill-down view to the main grouped overview."""
        self._active_group = None
        self._view_stack.setCurrentIndex(0)

    def _open_active_group_folder(self) -> None:
        """Open the target directory of the current active group."""
        if self._active_group and self._active_group.folder_path:
            self._open_folder(self._active_group.folder_path)

    def _on_group_cell_double_clicked(self, row: int, column: int) -> None:
        """Open group details on double-click."""
        if 0 <= row < len(self._displayed_groups):
            self._show_group_details(self._displayed_groups[row])

    def _on_group_cell_clicked(self, row: int, column: int) -> None:
        """Open group details on single click on title column."""
        if column == 0 and 0 <= row < len(self._displayed_groups):
            self._show_group_details(self._displayed_groups[row])

    def _on_detail_cell_double_clicked(self, row: int, column: int) -> None:
        """Play media on detail row double-click."""
        if self._active_group and 0 <= row < len(self._active_group.records):
            record = self._active_group.records[row]
            if record.output_path:
                self._play_file(record.output_path)

    def _open_folder(self, file_path: str) -> None:
        """Open parent directory in Windows File Explorer."""
        if not file_path:
            return
        p = Path(file_path).resolve()
        folder = p.parent if p.is_file() else p
        if folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _play_file(self, file_path: str) -> None:
        """Launch downloaded media in the system default media player."""
        if not file_path:
            return
        p = Path(file_path).resolve()
        if p.exists() and p.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _delete_record(self, task_id: str) -> None:
        """Delete an individual record from the database and refresh views."""
        try:
            self.repo.delete(task_id)
            self._all_records = [r for r in self._all_records if r.task_id != task_id]
            self._all_groups = group_records(self._all_records)
            self._apply_filters()

            # Refresh active group if still in detail view
            if self._active_group:
                updated_active = next(
                    (g for g in self._all_groups if g.base_title == self._active_group.base_title and g.date_key == self._active_group.date_key),
                    None,
                )
                if updated_active and updated_active.records:
                    self._show_group_details(updated_active)
                else:
                    self._navigate_back_to_groups()
        except Exception as exc:
            logger.error("Failed deleting record %s: %s", task_id, exc)

    def _delete_group(self, group: HistoryGroup) -> None:
        """Prompt confirmation and delete all records belonging to a group."""
        msg = f"Delete all {group.total_count} records for '{group.base_title}' from history?\n(Files on disk will not be deleted)"
        reply = QMessageBox.question(
            self,
            "Delete Download Group",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                for r in group.records:
                    self.repo.delete(r.task_id)
                self._all_records = [r for r in self._all_records if r not in group.records]
                self._all_groups = group_records(self._all_records)
                self._apply_filters()
            except Exception as exc:
                logger.error("Failed deleting group %s: %s", group.base_title, exc)

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
                self._all_groups.clear()
                self._apply_filters()
                self._navigate_back_to_groups()
            except Exception as exc:
                logger.error("Failed clearing history: %s", exc)

    def _update_summary(self) -> None:
        """Update bottom summary count and total disk usage."""
        total_groups = len(self._displayed_groups)
        total_files = sum(g.total_count for g in self._displayed_groups)
        total_bytes = sum(g.total_bytes for g in self._displayed_groups)
        self._summary_label.setText(
            f"Total Sessions: {total_groups} | Total Files: {total_files} ({format_bytes(total_bytes)})"
        )
