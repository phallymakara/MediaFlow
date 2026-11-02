"""Drama preview and episode inspection dialog."""

import logging
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.styles import COLORS
from app.services.drama_catalog_service import DramaCatalogItem, DramaCatalogService

logger = logging.getLogger(__name__)


class CoverImageLoader(QThread):
    """Background loader for remote cover image pixmap."""

    image_loaded = Signal(QPixmap)

    def __init__(self, url: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.url = url

    def run(self) -> None:
        if not self.url:
            return
        try:
            import httpx

            with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                resp = client.get(self.url)
                if resp.status_code == 200:
                    pix = QPixmap()
                    if pix.loadFromData(resp.content):
                        self.image_loaded.emit(pix)
        except Exception:
            pass


class DramaPreviewDialog(QDialog):
    """Modal dialog displaying short drama overview, episode list, and preview actions."""

    download_requested = Signal(str)

    def __init__(self, drama: DramaCatalogItem, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.drama = drama
        self._service = DramaCatalogService()

        self.setWindowTitle(f"Drama Details - {drama.title}")
        self.setMinimumSize(780, 640)
        self.resize(840, 680)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {COLORS.bg_window};
                color: {COLORS.text_primary};
            }}
            QFrame#cardFrame {{
                background-color: {COLORS.bg_surface};
                border: 1px solid {COLORS.border_subtle};
                border-radius: 8px;
            }}
            QLabel#dialogTitle {{
                font-size: 18px;
                font-weight: 700;
                color: {COLORS.text_primary};
            }}
            QLabel#dialogDesc {{
                font-size: 13px;
                line-height: 1.4;
                color: {COLORS.text_secondary};
            }}
            """
        )

        self._init_ui()
        self._load_cover()
        self._populate_episodes_async()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # 1. Top Drama Overview Card
        top_card = QFrame(self)
        top_card.setObjectName("cardFrame")
        top_layout = QHBoxLayout(top_card)
        top_layout.setContentsMargins(16, 16, 16, 16)
        top_layout.setSpacing(18)

        # Poster label
        self._poster_label = QLabel(top_card)
        self._poster_label.setFixedSize(140, 195)
        self._poster_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._poster_label.setStyleSheet(
            f"background-color: {COLORS.bg_input}; border-radius: 6px; color: {COLORS.text_muted};"
        )
        self._poster_label.setText("Loading Cover...")
        top_layout.addWidget(self._poster_label)

        # Info side
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(8)

        # Title
        title_lbl = QLabel(self.drama.title, top_card)
        title_lbl.setObjectName("dialogTitle")
        title_lbl.setWordWrap(True)
        info_layout.addWidget(title_lbl)

        # Platform and Episode metadata (direct on layout, no nested container)
        platform_color = (
            "#00F2FE" if self.drama.platform == "TikTok" else ("#A855F7" if self.drama.platform == "DramaBox" else "#F97316")
        )
        author_suffix = f" • By {self.drama.author}" if self.drama.author else ""
        meta_lbl = QLabel(f"{self.drama.platform} • {self.drama.episodes_count} Episodes{author_suffix}", top_card)
        meta_lbl.setStyleSheet(f"color: {platform_color}; font-weight: 700; font-size: 12px;")
        info_layout.addWidget(meta_lbl)

        # Tags
        if self.drama.tags:
            tags_str = " • ".join(self.drama.tags[:4])
            tags_lbl = QLabel(tags_str, top_card)
            tags_lbl.setStyleSheet(f"color: {COLORS.accent_primary}; font-size: 11px; font-weight: 600;")
            info_layout.addWidget(tags_lbl)

        # Description
        desc_scroll = QScrollArea(top_card)
        desc_scroll.setWidgetResizable(True)
        desc_scroll.setFixedHeight(75)
        desc_scroll.setFrameShape(QFrame.Shape.NoFrame)
        desc_scroll.setStyleSheet("background: transparent;")

        desc_lbl = QLabel(self.drama.description or "No synopsis available.", desc_scroll)
        desc_lbl.setObjectName("dialogDesc")
        desc_lbl.setWordWrap(True)
        desc_scroll.setWidget(desc_lbl)
        info_layout.addWidget(desc_scroll)

        top_layout.addLayout(info_layout, 1)
        main_layout.addWidget(top_card)

        # 2. Episode Catalog Section Header
        episodes_header_layout = QHBoxLayout()
        episodes_title = QLabel("Episode Catalog & Preview", self)
        episodes_title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {COLORS.text_primary};")
        episodes_header_layout.addWidget(episodes_title)

        self._status_label = QLabel("Loading episodes...", self)
        self._status_label.setStyleSheet(f"font-size: 12px; color: {COLORS.text_muted};")
        episodes_header_layout.addWidget(self._status_label)
        episodes_header_layout.addStretch()

        self._preview_btn = QPushButton("▶ Play Preview Stream", self)
        self._preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._preview_btn.setStyleSheet(
            f"background-color: {COLORS.bg_surface}; color: {COLORS.accent_primary}; border: 1px solid {COLORS.accent_primary}; border-radius: 4px; padding: 6px 12px; font-weight: 600;"
        )
        self._preview_btn.clicked.connect(self._on_play_preview_clicked)
        self._preview_btn.setEnabled(False)
        episodes_header_layout.addWidget(self._preview_btn)

        main_layout.addLayout(episodes_header_layout)

        # 3. Episodes Table
        self._table = QTableWidget(self)
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["#", "Title", "Duration", "Status"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(
            f"""
            QTableWidget {{
                background-color: {COLORS.bg_surface};
                border: 1px solid {COLORS.border_subtle};
                border-radius: 6px;
                gridline-color: {COLORS.border_subtle};
                color: {COLORS.text_primary};
            }}
            QHeaderView::section {{
                background-color: {COLORS.bg_input};
                color: {COLORS.text_secondary};
                padding: 6px;
                border: none;
                font-weight: 600;
            }}
            """
        )
        main_layout.addWidget(self._table, 1)

        # 4. Bottom Button Row
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self._url_display = QLabel(self.drama.url, self)
        self._url_display.setStyleSheet(f"color: {COLORS.text_muted}; font-size: 11px;")
        btn_layout.addWidget(self._url_display, 1)

        close_btn = QPushButton("Close", self)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"background-color: {COLORS.bg_surface}; color: {COLORS.text_primary}; border: 1px solid {COLORS.border_subtle}; border-radius: 6px; padding: 8px 16px;"
        )
        close_btn.clicked.connect(self.reject)
        btn_layout.addWidget(close_btn)

        download_btn = QPushButton("⬇ Download Drama", self)
        download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        download_btn.setStyleSheet(
            f"background-color: {COLORS.accent_primary}; color: #ffffff; font-weight: 700; border-radius: 6px; padding: 8px 20px;"
        )
        download_btn.clicked.connect(self._on_download_clicked)
        btn_layout.addWidget(download_btn)

        main_layout.addLayout(btn_layout)

    def _load_cover(self) -> None:
        """Trigger background image download for the cover."""
        if self.drama.cover_url:
            self._loader = CoverImageLoader(self.drama.cover_url, self)
            self._loader.image_loaded.connect(self._on_cover_loaded)
            self._loader.start()

    def _on_cover_loaded(self, pixmap: QPixmap) -> None:
        scaled = pixmap.scaled(
            self._poster_label.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._poster_label.setPixmap(scaled)

    def _populate_episodes_async(self) -> None:
        """Fetch real episode details in a background worker."""
        from app.services.drama_catalog_service import DramaCatalogWorker

        self._worker = DramaCatalogWorker(parent=self)
        self._worker.set_detail_target(self.drama)
        self._worker.drama_detailed.connect(self._on_detail_loaded)
        self._worker.start()

    def _on_detail_loaded(self, item: DramaCatalogItem) -> None:
        self.drama = item
        self._table.setRowCount(0)

        eps = item.episodes
        is_tiktok = item.platform.lower() == "tiktok"
        if not eps:
            self._status_label.setText(f"{item.episodes_count} episodes listed (Stream extraction on download).")
            # Build placeholder rows
            for sn in range(1, min(item.episodes_count + 1, 100)):
                row = self._table.rowCount()
                self._table.insertRow(row)
                self._table.setItem(row, 0, QTableWidgetItem(f"{sn:02d}"))
                self._table.setItem(row, 1, QTableWidgetItem(f"Episode {sn:02d}"))
                self._table.setItem(row, 2, QTableWidgetItem("~1 min"))
                if is_tiktok:
                    status_item = QTableWidgetItem("Free / Public")
                    status_item.setForeground(QColor(COLORS.status_success))
                else:
                    is_free = sn <= 5
                    status_item = QTableWidgetItem("Free" if is_free else "Locked / VIP")
                    status_item.setForeground(
                        QColor(COLORS.status_success if is_free else COLORS.status_warning)
                    )
                self._table.setItem(row, 3, status_item)
        else:
            self._status_label.setText(f"{len(eps)} episodes available.")
            for ep in eps:
                row = self._table.rowCount()
                self._table.insertRow(row)
                self._table.setItem(row, 0, QTableWidgetItem(f"{ep.episode_number:02d}"))
                self._table.setItem(row, 1, QTableWidgetItem(ep.title))
                dur_str = f"{ep.duration_seconds}s" if ep.duration_seconds else "-"
                self._table.setItem(row, 2, QTableWidgetItem(dur_str))
                is_ep_locked = ep.is_locked and not is_tiktok
                status_item = QTableWidgetItem("Locked" if is_ep_locked else "Free / Unlocked")
                status_item.setForeground(
                    QColor(COLORS.status_warning if is_ep_locked else COLORS.status_success)
                )
                self._table.setItem(row, 3, status_item)

        if item.preview_video_url:
            self._preview_btn.setEnabled(True)
            self._preview_btn.setText("▶ Play Preview Stream")

    def _on_play_preview_clicked(self) -> None:
        """Open preview stream in system default player or video handler."""
        if not self.drama.preview_video_url:
            return
        import webbrowser
        webbrowser.open(self.drama.preview_video_url)

    def _on_download_clicked(self) -> None:
        """Trigger download signal and close dialog."""
        self.download_requested.emit(self.drama.url)
        self.accept()

