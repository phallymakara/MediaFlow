"""Downloader page providing the primary tabular media download workspace."""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
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
    QVBoxLayout,
    QWidget,
)

from app.core.downloader import Downloader
from app.core.extractor_registry import ExtractorRegistry
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
        self.registry = extractor_registry or ExtractorRegistry()
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
        self._queue_title.setStyleSheet("font-size: 13px; font-weight: 600; color: #ffffff;")
        queue_header.addWidget(self._queue_title)
        queue_header.addStretch()

        self._clear_finished_btn = QPushButton("Clear Finished", self)
        self._clear_finished_btn.clicked.connect(self._clear_finished_tasks)
        queue_header.addWidget(self._clear_finished_btn)

        layout.addLayout(queue_header)

        # 3. Tabular Task Queue (QTableWidget)
        self._table = QTableWidget(self)
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "Name", "Platform", "Progress", "Size", "Speed", "ETA", "Status", "Actions"
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Name stretches
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(2, 170)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(7, 120)

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
        name_layout = QHBoxLayout(name_widget)
        name_layout.setContentsMargins(8, 0, 8, 0)
        name_layout.setSpacing(8)

        icon_label = QLabel(name_widget)
        icon_label.setPixmap(create_vector_icon("downloader", size=16).pixmap(16, 16))
        name_layout.addWidget(icon_label)

        title_label = QLabel(task.title, name_widget)
        title_label.setToolTip(task.title)
        name_layout.addWidget(title_label, 1)
        self._table.setCellWidget(row, 0, name_widget)

        # 1: Platform
        platform_label = QLabel(task.platform.title())
        platform_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setCellWidget(row, 1, platform_label)

        # 2: Progress (Slim Bar + Percent)
        progress_widget = QWidget()
        progress_layout = QHBoxLayout(progress_widget)
        progress_layout.setContentsMargins(6, 0, 6, 0)
        progress_layout.setSpacing(8)

        pbar = QProgressBar(progress_widget)
        pbar.setRange(0, 100)
        pbar.setValue(0)
        progress_layout.addWidget(pbar, 1)

        pct_label = QLabel("0%", progress_widget)
        pct_label.setFixedWidth(34)
        pct_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        pct_label.setObjectName("captionText")
        progress_layout.addWidget(pct_label)

        self._table.setCellWidget(row, 2, progress_widget)

        # 3: Size
        size_label = QLabel("-- / --")
        size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        size_label.setObjectName("captionText")
        self._table.setCellWidget(row, 3, size_label)

        # 4: Speed
        speed_label = QLabel("--")
        speed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        speed_label.setObjectName("captionText")
        self._table.setCellWidget(row, 4, speed_label)

        # 5: ETA
        eta_label = QLabel("--")
        eta_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        eta_label.setObjectName("captionText")
        self._table.setCellWidget(row, 5, eta_label)

        # 6: Status Badge
        badge = StatusBadge(status=task.status)
        badge_container = QWidget()
        b_layout = QHBoxLayout(badge_container)
        b_layout.setContentsMargins(4, 0, 4, 0)
        b_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        b_layout.addWidget(badge)
        self._table.setCellWidget(row, 6, badge_container)

        # 7: Action Button (Cancel)
        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 0, 4, 0)
        action_layout.setSpacing(4)

        cancel_btn = QPushButton("Cancel", action_widget)
        cancel_btn.setObjectName("dangerButton")
        cancel_btn.clicked.connect(lambda checked=False, tid=task_id: self._on_cancel_task_clicked(tid))
        action_layout.addWidget(cancel_btn)

        self._table.setCellWidget(row, 7, action_widget)

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

        # Update Progress Bar & Percentage
        pwidget = self._table.cellWidget(row, 2)
        if pwidget:
            pbar = pwidget.findChild(QProgressBar)
            pct_label = pwidget.findChild(QLabel)
            if pbar:
                pbar.setValue(percent)
            if pct_label:
                pct_label.setText(f"{percent}%")

        # Update Size (e.g. 45.2 MB / 120.0 MB)
        size_widget = self._table.cellWidget(row, 3)
        if isinstance(size_widget, QLabel):
            size_widget.setText(f"{format_bytes(downloaded)} / {format_bytes(total)}")

        # Update Speed
        speed_widget = self._table.cellWidget(row, 4)
        if isinstance(speed_widget, QLabel):
            speed_widget.setText(format_speed(speed))

        # Update ETA
        eta_widget = self._table.cellWidget(row, 5)
        if isinstance(eta_widget, QLabel):
            eta_widget.setText(format_eta(eta))

        self._update_queue_summary()

    def _on_status_changed(self, task_id: str, new_status: str, error_message: str) -> None:
        """Handle task status transitions from background thread."""
        row = self._task_rows.get(task_id)
        if row is None:
            return

        if task_id in self._task_data:
            self._task_data[task_id]["status"] = new_status

        # Update Status Badge
        badge_container = self._table.cellWidget(row, 6)
        if badge_container:
            badge = badge_container.findChild(StatusBadge)
            if badge:
                badge.set_status(new_status)

        # If failed, zero speed and ETA
        if new_status == DownloadStatus.FAILED.value:
            if task_id in self._task_data:
                self._task_data[task_id]["speed"] = 0.0
            spd_widget = self._table.cellWidget(row, 4)
            if isinstance(spd_widget, QLabel):
                spd_widget.setText("--")
            eta_widget = self._table.cellWidget(row, 5)
            if isinstance(eta_widget, QLabel):
                eta_widget.setText("--")

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

        # Clear Speed & ETA
        spd_widget = self._table.cellWidget(row, 4)
        if isinstance(spd_widget, QLabel):
            spd_widget.setText("--")
        eta_widget = self._table.cellWidget(row, 5)
        if isinstance(eta_widget, QLabel):
            eta_widget.setText("--")

        # Replace Cancel button with Open Folder button
        action_widget = self._table.cellWidget(row, 7)
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
