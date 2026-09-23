"""Downloader page providing the primary tabular media download workspace."""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QEvent, QObject, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.downloader import Downloader
from app.core.extractor_registry import ExtractorRegistry, get_default_registry
from app.core.media import MediaEpisode, MediaInfo
from app.core.tasks import DownloadTask
from app.database.models import DownloadStatus
from app.gui.assets import create_vector_icon
from app.gui.dialogs.episode_picker import EpisodePickerDialog
from app.gui.styles import COLORS
from app.gui.widgets.status_badge import StatusBadge
from app.gui.workers import AnalyzeWorker, DownloadSignalBridge
from app.services.license import LicenseService

logger = logging.getLogger(__name__)


def format_bytes(bytes_count: int) -> str:
    """Format raw byte counts into human-readable strings (e.g. 142.5 MB)."""
    if bytes_count <= 0:
        return "--"
    val = float(bytes_count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024.0:
            return f"{val:.1f} {unit}"
        val /= 1024.0
    return f"{val:.1f} PB"


def format_speed(bytes_per_sec: float) -> str:
    """Format speed values into human-readable strings (e.g. 8.6 MB/s)."""
    if bytes_per_sec <= 0:
        return "--"
    if bytes_per_sec < 1024 * 1024:
        return f"{bytes_per_sec / 1024:.1f} KB/s"
    return f"{bytes_per_sec / (1024 * 1024):.1f} MB/s"


def format_eta(seconds: Optional[int]) -> str:
    """Format remaining seconds into human-readable duration (e.g. 24s or 1m 15s)."""
    if seconds is None or seconds <= 0:
        return "--"
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    rem_seconds = seconds % 60
    if minutes < 60:
        return f"{minutes}m {rem_seconds:02d}s"
    hours = minutes // 60
    rem_minutes = minutes % 60
    return f"{hours}h {rem_minutes:02d}m"


def format_speed_eta(bytes_per_sec: float, seconds: Optional[int]) -> str:
    """Format speed and remaining ETA into a unified compact string.

    Examples:
        - "5.2 MB/s • 45s left"
        - "850.0 KB/s • 1m 12s left"
        - "2.1 MB/s" (if ETA is not yet computed)
        - "--" (if speed is zero or inactive)
    """
    speed_str = format_speed(bytes_per_sec)
    if speed_str == "--":
        return "--"

    eta_str = format_eta(seconds)
    if eta_str == "--":
        return speed_str

    return f"{speed_str} • {eta_str} left"


class DownloaderPage(QWidget):
    """Main downloader page hosting URL control bar, high-density task queue, and status strip."""

    def __init__(
        self,
        downloader: Optional[Downloader] = None,
        extractor_registry: Optional[ExtractorRegistry] = None,
        license_service: Optional[LicenseService] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize downloader workspace.

        Args:
            downloader: Background downloader instance.
            extractor_registry: Extractor registry for URL inspection.
            license_service: License service for permission checks.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.downloader = downloader or Downloader()
        self.registry = extractor_registry or get_default_registry()

        self.license_service = license_service or LicenseService()

        self._signal_bridge = DownloadSignalBridge()
        self._signal_bridge.progress_updated.connect(self._on_progress_updated)
        self._signal_bridge.status_changed.connect(self._on_status_changed)
        self._signal_bridge.task_completed.connect(self._on_task_completed)

        self._task_rows: Dict[str, int] = {}
        self._row_tasks: Dict[int, str] = {}
        self._task_data: Dict[str, Dict] = {}

        self._current_worker: Optional[AnalyzeWorker] = None

        self._init_ui()

    def _init_ui(self) -> None:
        """Construct the Downloader page layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # 1. Top URL Input Bar
        top_container = QWidget(self)
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(6)

        control_bar = QHBoxLayout()
        control_bar.setSpacing(8)

        self._url_input = QLineEdit(self)
        self._url_input.setPlaceholderText("Paste video or drama URL from YouTube, TikTok, DramaBox, or direct link...")
        self._url_input.returnPressed.connect(self._on_add_download_clicked)
        self._url_input.textChanged.connect(self._clear_input_error)
        control_bar.addWidget(self._url_input, 1)

        paste_btn = QPushButton("Paste", self)
        paste_btn.clicked.connect(self._on_paste_clicked)
        control_bar.addWidget(paste_btn)

        self._format_combo = QComboBox(self)
        self._format_combo.addItems(["1080p MP4", "720p MP4", "480p MP4", "Audio Only MP3"])
        control_bar.addWidget(self._format_combo)

        self._add_btn = QPushButton("Add Download", self)
        self._add_btn.setObjectName("primaryButton")
        self._add_btn.clicked.connect(self._on_add_download_clicked)
        control_bar.addWidget(self._add_btn)

        top_layout.addLayout(control_bar)

        self._error_label = QLabel(self)
        self._error_label.setObjectName("errorText")
        self._error_label.hide()
        top_layout.addWidget(self._error_label)

        layout.addWidget(top_container)

        # 2. Queue Header Toolbar
        queue_header = QHBoxLayout()
        self._queue_title = QLabel("Active Downloads (0 tasks)", self)
        self._queue_title.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLORS.text_primary};")
        queue_header.addWidget(self._queue_title)
        queue_header.addStretch()

        self._clear_finished_btn = QPushButton("Clear Finished", self)
        self._clear_finished_btn.clicked.connect(self._clear_finished_tasks)
        queue_header.addWidget(self._clear_finished_btn)

        layout.addLayout(queue_header)

        # 3. Tabular Task Queue (QTableWidget)
        self._table = QTableWidget(self)
        self._table.setColumnCount(6)
        headers = ["Name", "Platform", "Progress", "Size", "Status", "Actions"]
        self._table.setHorizontalHeaderLabels(headers)
        header_tooltips = {
            0: "Media name and title",
            1: "Platform source",
            2: "Download completion percentage and progress bar",
            3: "Downloaded size / Total file size",
            4: "Current task status",
            5: "Task actions",
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
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.setMouseTracking(True)
        self._table.viewport().setMouseTracking(True)
        self._table.viewport().installEventFilter(self)
        self._hovered_row: int = -1
        self._table.setStyleSheet(
            f"QTableWidget {{ background-color: {COLORS.bg_window}; border: 1px solid {COLORS.border_subtle}; border-radius: 6px; }}"
            f"QTableWidget::item {{ background-color: {COLORS.bg_window}; color: {COLORS.text_primary}; }}"
            f"QTableWidget::item:hover {{ background-color: {COLORS.bg_hover}; }}"
            f"QTableWidget QWidget {{ background-color: transparent; }}"
        )

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Name stretches
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(1, 85)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(2, 160)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(5, 110)

        layout.addWidget(self._table, 1)

        # 4. Bottom Status Strip
        bottom_strip = QHBoxLayout()
        bottom_strip.setContentsMargins(4, 4, 4, 4)

        self._summary_label = QLabel("Queue: 0 Downloading, 0 Queued, 0 Completed", self)
        self._summary_label.setObjectName("captionText")
        bottom_strip.addWidget(self._summary_label)

        bottom_strip.addStretch()

        self._speed_label = QLabel("Total Speed: 0.0 MB/s", self)
        self._speed_label.setObjectName("captionText")
        bottom_strip.addWidget(self._speed_label)

        layout.addLayout(bottom_strip)

    def _on_paste_clicked(self) -> None:
        """Paste clipboard content directly into the URL input."""
        clipboard = QGuiApplication.clipboard()
        text = clipboard.text().strip()
        if text:
            self._url_input.setText(text)
            self._clear_input_error()

    def _clear_input_error(self) -> None:
        """Clear error status and restore default input borders."""
        self._error_label.hide()
        self._url_input.setObjectName("")
        self._url_input.style().unpolish(self._url_input)
        self._url_input.style().polish(self._url_input)

    def _show_input_error(self, message: str) -> None:
        """Display an inline error message directly below the URL input."""
        self._error_label.setText(message)
        self._error_label.show()
        self._url_input.setObjectName("inputError")
        self._url_input.style().unpolish(self._url_input)
        self._url_input.style().polish(self._url_input)

    def _on_add_download_clicked(self) -> None:
        """Trigger asynchronous media extraction and queue submission."""
        url = self._url_input.text().strip()
        self._clear_input_error()

        if not url:
            self._show_input_error("Please enter a media URL.")
            return

        if not self.license_service.is_download_allowed():
            self._show_input_error("Active license required to start downloads. Please activate on the License page.")
            return

        self._add_btn.setEnabled(False)
        self._add_btn.setText("Analyzing...")

        self._current_worker = AnalyzeWorker(url=url, extractor_registry=self.registry, parent=self)
        self._current_worker.analysis_success.connect(self._on_analysis_success)
        self._current_worker.analysis_failed.connect(self._on_analysis_failed)
        self._current_worker.start()

    def _on_analysis_success(self, media_info: MediaInfo) -> None:
        """Handle resolved metadata and enqueue single download or drama episodes."""
        self._add_btn.setEnabled(True)
        self._add_btn.setText("Add Download")

        selected_format = self._format_combo.currentText()

        # Handle Short Drama multi-episode series
        if media_info.episodes and len(media_info.episodes) > 1:
            dialog = EpisodePickerDialog(media_info=media_info, parent=self)
            if dialog.exec():
                selected_eps: List[MediaEpisode] = dialog.get_selected_episodes()
                chosen_format = dialog.get_selected_format()
                for ep in selected_eps:
                    self._enqueue_task(
                        url=ep.url,
                        title=f"{media_info.title} - Ep {ep.episode_number:02d}",
                        platform=media_info.platform,
                        format_str=chosen_format,
                        thumbnail_url=media_info.thumbnail_url,
                    )
                self._url_input.clear()
            return

        # Single media download
        self._enqueue_task(
            url=media_info.url,
            title=media_info.title,
            platform=media_info.platform,
            format_str=selected_format,
            thumbnail_url=media_info.thumbnail_url,
        )
        self._url_input.clear()

    def _on_analysis_failed(self, error_message: str) -> None:
        """Handle media extraction failure safely."""
        self._add_btn.setEnabled(True)
        self._add_btn.setText("Add Download")
        self._show_input_error(error_message)

    def _enqueue_task(
        self,
        url: str,
        title: str,
        platform: str,
        format_str: str,
        thumbnail_url: Optional[str] = None,
    ) -> None:
        """Enqueue task into downloader and insert a new row in task queue table."""
        try:
            task: DownloadTask = self.downloader.submit(
                url=url,
                title=title,
                platform=platform,
                format_id=format_str,
                quality=format_str,
                thumbnail_url=thumbnail_url,
                on_progress=self._signal_bridge.on_progress,
                on_status_change=self._signal_bridge.on_status_change,
            )
            self._add_table_row(task)
            self._update_queue_summary()
        except Exception as exc:
            logger.error("Failed enqueuing task: %s", exc)
            self._show_input_error("Could not schedule download. Please verify storage permissions.")

    def _add_table_row(self, task: DownloadTask) -> None:
        """Insert a new row into the active QTableWidget."""
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setRowHeight(row, 46)

        # Initialize uniform dark background items for each column in this row
        for c in range(self._table.columnCount()):
            it = QTableWidgetItem()
            it.setBackground(QColor(COLORS.bg_window))
            self._table.setItem(row, c, it)

        task_id = task.task_id
        self._task_rows[task_id] = row
        self._row_tasks[row] = task_id
        self._task_data[task_id] = {
            "title": task.title,
            "platform": task.platform,
            "speed": 0.0,
            "output_path": str(task.output_path),
            "status": task.status.value,
        }

        # 0: Name (Icon + Title)
        name_widget = QWidget()
        name_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        name_widget.setStyleSheet("background: transparent;")
        name_layout = QHBoxLayout(name_widget)
        name_layout.setContentsMargins(8, 0, 8, 0)
        name_layout.setSpacing(8)

        icon_label = QLabel(name_widget)
        icon_label.setStyleSheet("background: transparent;")
        icon_label.setPixmap(create_vector_icon("downloader", size=16).pixmap(16, 16))
        name_layout.addWidget(icon_label)

        title_label = QLabel(task.title, name_widget)
        title_label.setStyleSheet(f"color: {COLORS.text_primary}; background: transparent;")
        title_label.setToolTip(task.title)
        name_layout.addWidget(title_label, 1)
        self._table.setCellWidget(row, 0, name_widget)

        # 1: Platform
        platform_label = QLabel(task.platform.title())
        platform_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        platform_label.setStyleSheet(f"color: {COLORS.text_secondary}; background: transparent;")
        platform_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setCellWidget(row, 1, platform_label)

        # 2: Progress (Thicker Bar with centered percentage inside)
        progress_widget = QWidget()
        progress_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        progress_widget.setStyleSheet("background: transparent;")
        progress_layout = QHBoxLayout(progress_widget)
        progress_layout.setContentsMargins(6, 0, 6, 0)
        progress_layout.setSpacing(0)

        pbar = QProgressBar(progress_widget)
        pbar.setRange(0, 100)
        pbar.setValue(0)
        pbar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pbar.setTextVisible(True)
        progress_layout.addWidget(pbar)

        self._table.setCellWidget(row, 2, progress_widget)

        # 3: Size
        size_label = QLabel("-- / --")
        size_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        size_label.setObjectName("captionText")
        size_label.setStyleSheet(f"color: {COLORS.text_muted}; background: transparent;")
        self._table.setCellWidget(row, 3, size_label)

        # 4: Status Badge
        badge = StatusBadge(status=task.status)
        badge_container = QWidget()
        badge_container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        badge_container.setStyleSheet("background: transparent;")
        b_layout = QHBoxLayout(badge_container)
        b_layout.setContentsMargins(4, 0, 4, 0)
        b_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b_layout.addWidget(badge)
        self._table.setCellWidget(row, 4, badge_container)

        # 5: Action Button (Cancel)
        action_widget = QWidget()
        action_widget.installEventFilter(self)
        action_widget.setStyleSheet("background: transparent;")
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 0, 4, 0)
        action_layout.setSpacing(4)

        cancel_btn = QPushButton("Cancel", action_widget)
        cancel_btn.setObjectName("dangerButton")
        cancel_btn.clicked.connect(lambda checked=False, tid=task_id: self._on_cancel_task_clicked(tid))
        action_layout.addWidget(cancel_btn)

        self._table.setCellWidget(row, 5, action_widget)

    def _on_progress_updated(
        self,
        task_id: str,
        downloaded: int,
        total: int,
        speed: float,
        eta: int,
        percent: int,
    ) -> None:
        """Handle real-time progress event from background thread."""
        row = self._task_rows.get(task_id)
        if row is None:
            return

        if task_id in self._task_data:
            self._task_data[task_id]["speed"] = speed

        # Update Progress Bar
        pwidget = self._table.cellWidget(row, 2)
        if pwidget:
            pbar = pwidget.findChild(QProgressBar)
            if pbar:
                pbar.setValue(int(percent))

        # Update Size (e.g. 45.2 MB / 120.0 MB)
        size_widget = self._table.cellWidget(row, 3)
        if isinstance(size_widget, QLabel):
            size_widget.setText(f"{format_bytes(downloaded)} / {format_bytes(total)}")

        self._update_queue_summary()

    def _on_status_changed(self, task_id: str, new_status: str, error_message: str) -> None:
        """Handle task status transitions from background thread."""
        row = self._task_rows.get(task_id)
        if row is None:
            return

        if task_id in self._task_data:
            self._task_data[task_id]["status"] = new_status

        # Update Status Badge
        badge_container = self._table.cellWidget(row, 4)
        if badge_container:
            badge = badge_container.findChild(StatusBadge)
            if badge:
                badge.set_status(new_status)

        # If failed, zero speed
        if new_status == DownloadStatus.FAILED.value:
            if task_id in self._task_data:
                self._task_data[task_id]["speed"] = 0.0

        self._update_queue_summary()

    def _on_task_completed(self, task_id: str, output_path: str) -> None:
        """Handle task completion event, updating progress bar and action buttons."""
        row = self._task_rows.get(task_id)
        if row is None:
            return

        if task_id in self._task_data:
            self._task_data[task_id]["speed"] = 0.0
            self._task_data[task_id]["output_path"] = output_path

        # Mark Progress bar as completed
        pwidget = self._table.cellWidget(row, 2)
        if pwidget:
            pbar = pwidget.findChild(QProgressBar)
            if pbar:
                pbar.setValue(100)
                pbar.setObjectName("progressCompleted")
                pbar.style().unpolish(pbar)
                pbar.style().polish(pbar)

        # Replace Cancel button with Open Folder button
        action_widget = self._table.cellWidget(row, 5)
        if action_widget:
            layout = action_widget.layout()
            # Clear old buttons
            while layout.count():
                child = layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            open_btn = QPushButton("Open Folder", action_widget)
            open_btn.setObjectName("rowActionButton")
            open_btn.clicked.connect(lambda checked=False, p=output_path: self._open_file_folder(p))
            layout.addWidget(open_btn)

        self._update_queue_summary()

    def _on_cancel_task_clicked(self, task_id: str) -> None:
        """Cancel the specified active download task."""
        self.downloader.cancel(task_id)

    def _open_file_folder(self, file_path: str) -> None:
        """Highlight or open target folder in Windows File Explorer."""
        p = Path(file_path).resolve()
        folder = p.parent if p.is_file() else p
        if folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _clear_finished_tasks(self) -> None:
        """Remove completed or cancelled rows from the active table display."""
        finished_statuses = (DownloadStatus.COMPLETED.value, DownloadStatus.CANCELLED.value)
        rows_to_delete = []

        for task_id, row in sorted(self._task_rows.items(), key=lambda x: x[1], reverse=True):
            status = self._task_data.get(task_id, {}).get("status")
            if status in finished_statuses:
                rows_to_delete.append((task_id, row))

        for task_id, row in rows_to_delete:
            self._table.removeRow(row)
            self._task_rows.pop(task_id, None)
            self._task_data.pop(task_id, None)

        # Re-index remaining task rows
        self._task_rows.clear()
        self._row_tasks.clear()
        for r in range(self._table.rowCount()):
            pass  # rows re-mapped naturally by next progress events

        self._update_queue_summary()

    def _update_queue_summary(self) -> None:
        """Update top and bottom summary counts and aggregate throughput."""
        total_tasks = len(self._task_data)
        downloading = sum(1 for d in self._task_data.values() if d.get("status") == DownloadStatus.DOWNLOADING.value)
        queued = sum(1 for d in self._task_data.values() if d.get("status") == DownloadStatus.QUEUED.value)
        completed = sum(1 for d in self._task_data.values() if d.get("status") == DownloadStatus.COMPLETED.value)

        self._queue_title.setText(f"Active Downloads ({total_tasks} tasks)")
        self._summary_label.setText(f"Queue: {downloading} Downloading, {queued} Queued, {completed} Completed")

        total_speed = sum(d.get("speed", 0.0) for d in self._task_data.values() if d.get("status") == DownloadStatus.DOWNLOADING.value)
        self._speed_label.setText(f"Total Speed: {format_speed(total_speed)}")

    def _set_row_hover(self, row: int, hovered: bool) -> None:
        """Update row background color on mouse hover."""
        if 0 <= row < self._table.rowCount():
            color = QColor(COLORS.bg_hover) if hovered else QColor(COLORS.bg_window)
            for c in range(self._table.columnCount()):
                item = self._table.item(row, c)
                if item:
                    item.setBackground(color)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Track mouse movement to smoothly highlight hovered rows."""
        if obj == self._table.viewport() or isinstance(obj, QWidget):
            if event.type() == QEvent.Type.MouseMove:
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                if obj != self._table.viewport() and isinstance(obj, QWidget):
                    pos = obj.mapTo(self._table.viewport(), pos)
                row = self._table.rowAt(pos.y())
                if row != self._hovered_row:
                    if self._hovered_row >= 0:
                        self._set_row_hover(self._hovered_row, False)
                    self._hovered_row = row
                    if self._hovered_row >= 0:
                        self._set_row_hover(self._hovered_row, True)
            elif event.type() == QEvent.Type.Leave:
                if self._hovered_row >= 0:
                    self._set_row_hover(self._hovered_row, False)
                    self._hovered_row = -1
        return super().eventFilter(obj, event)

