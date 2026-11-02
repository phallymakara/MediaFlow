"""Short Drama Explorer page with high-performance lazy loading and caching."""

import hashlib
import logging
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.gui.dialogs.drama_preview_dialog import DramaPreviewDialog
from app.gui.styles import COLORS
from app.services.drama_catalog_service import (
    CACHE_DIR,
    DramaCatalogItem,
    DramaCatalogService,
    DramaCatalogWorker,
)

logger = logging.getLogger(__name__)

# In-memory pixmap cache to prevent duplicate image rendering
IMAGE_MEMORY_CACHE: Dict[str, QPixmap] = {}


class LazyCoverLoader(QThread):
    """Background thumbnail loader with disk and memory caching."""

    cover_loaded = Signal(str, QPixmap)

    def __init__(self, drama_id: str, url: str, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.drama_id = drama_id
        self.url = url

    def run(self) -> None:
        if not self.url:
            return

        # 1. Check disk cache first
        cached_path = DramaCatalogService.get_cached_cover_path(self.url)
        if cached_path:
            pix = QPixmap()
            if pix.load(str(cached_path)):
                IMAGE_MEMORY_CACHE[self.url] = pix
                self.cover_loaded.emit(self.drama_id, pix)
                return

        # 2. Download and save to disk cache
        try:
            import httpx

            with httpx.Client(timeout=6.0, follow_redirects=True) as client:
                resp = client.get(self.url)
                if resp.status_code == 200 and len(resp.content) > 500:
                    pix = QPixmap()
                    if pix.loadFromData(resp.content):
                        DramaCatalogService.save_cached_cover(self.url, resp.content)
                        IMAGE_MEMORY_CACHE[self.url] = pix
                        self.cover_loaded.emit(self.drama_id, pix)
        except Exception:
            pass


class DramaCardWidget(QFrame):
    """Card widget representing a short drama in the grid catalog."""

    preview_clicked = Signal(object)

    def __init__(self, item: DramaCatalogItem, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.item = item
        self.setMinimumWidth(170)
        self.setMaximumWidth(240)
        self.setFixedHeight(340)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"""
            QFrame {{
                background-color: {COLORS.bg_surface};
                border: 1px solid {COLORS.border_subtle};
                border-radius: 8px;
            }}
            QFrame:hover {{
                border: 1px solid {COLORS.accent_primary};
                background-color: {COLORS.bg_hover};
            }}
            QLabel#cardTitle {{
                font-weight: 700;
                font-size: 13px;
                color: {COLORS.text_primary};
                line-height: 1.2;
            }}
            """
        )

        self._init_ui()
        self._load_thumbnail_cached()

    def mousePressEvent(self, event) -> None:
        """Clicking anywhere on the card opens episode preview (does not download)."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.preview_clicked.emit(self.item)
        super().mousePressEvent(event)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # 1. Poster Cover Image (direct on layout, no nested container)
        self._cover_lbl = QLabel(self)
        self._cover_lbl.setFixedHeight(215)
        self._cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_lbl.setStyleSheet(
            f"background-color: {COLORS.bg_input}; border-radius: 6px; color: {COLORS.text_muted}; font-size: 11px;"
        )
        self._cover_lbl.setText("Loading Cover...")
        layout.addWidget(self._cover_lbl)

        # 2. Title of the Drama (direct on layout, no nested container)
        title_text = self.item.title
        if len(title_text) > 34:
            title_text = title_text[:31] + "..."
        self._title_lbl = QLabel(title_text, self)
        self._title_lbl.setObjectName("cardTitle")
        self._title_lbl.setToolTip(self.item.title)
        layout.addWidget(self._title_lbl)

        # 3. Number of Episodes & Platform (direct on layout, no nested container)
        platform_color = (
            "#00F2FE" if self.item.platform == "TikTok" else ("#A855F7" if self.item.platform == "DramaBox" else "#F97316")
        )
        self._meta_lbl = QLabel(f"{self.item.platform} • {self.item.episodes_count} Episodes", self)
        self._meta_lbl.setStyleSheet(f"color: {platform_color}; font-size: 11px; font-weight: 600;")
        layout.addWidget(self._meta_lbl)

        layout.addStretch(1)

        # 4. View Episodes Button (direct on layout, no nested container)
        view_btn = QPushButton("View Episodes", self)
        view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        view_btn.setFixedHeight(28)
        view_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {COLORS.bg_input};
                color: {COLORS.text_primary};
                border: 1px solid {COLORS.border_subtle};
                border-radius: 5px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {COLORS.accent_primary};
                color: #ffffff;
                border: 1px solid {COLORS.accent_primary};
            }}
            """
        )
        view_btn.clicked.connect(lambda: self.preview_clicked.emit(self.item))
        layout.addWidget(view_btn)

    def _load_thumbnail_cached(self) -> None:
        """Check cache and render instantly if available."""
        url = self.item.cover_url
        if not url:
            self._cover_lbl.setText("No Cover")
            return

        # 1. Memory cache check
        if url in IMAGE_MEMORY_CACHE:
            self.set_cover_pixmap(IMAGE_MEMORY_CACHE[url])
            return

        # 2. Disk cache check
        disk_file = DramaCatalogService.get_cached_cover_path(url)
        if disk_file:
            pix = QPixmap()
            if pix.load(str(disk_file)):
                IMAGE_MEMORY_CACHE[url] = pix
                self.set_cover_pixmap(pix)
                return

    def set_cover_pixmap(self, pixmap: QPixmap) -> None:
        """Render cover pixmap with smooth aspect ratio scaling."""
        scaled = pixmap.scaled(
            self._cover_lbl.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._cover_lbl.setPixmap(scaled)


class ShortDramaPage(QWidget):
    """High-performance short drama explorer with infinite-scroll lazy loading."""

    request_download = Signal(str)

    BATCH_SIZE: int = 16  # Render 16 cards per page chunk

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("dramaPage")

        self._all_dramas: List[DramaCatalogItem] = []
        self._filtered_dramas: List[DramaCatalogItem] = []
        self._rendered_count: int = 0
        self._active_filter: str = "All"
        self._card_widgets: Dict[str, DramaCardWidget] = {}
        self._active_loaders: List[LazyCoverLoader] = []
        self._current_cols: int = 4

        self._init_ui()
        self.refresh_catalog()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # 1. Search & Modern Capsule Filter Chips
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(14)

        self._search_input = QLineEdit(self)
        self._search_input.setPlaceholderText("Search short drama title, genre, or paste URL...")
        self._search_input.setFixedHeight(38)
        self._search_input.setStyleSheet(
            f"""
            QLineEdit {{
                background-color: {COLORS.bg_input};
                border: 1px solid {COLORS.border_subtle};
                border-radius: 8px;
                padding: 0 14px;
                color: {COLORS.text_primary};
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border: 1px solid {COLORS.border_focus};
            }}
            """
        )
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self._search_input.returnPressed.connect(self._on_search_entered)
        toolbar.addWidget(self._search_input, 1)

        # Capsule Filter Chips
        filter_container = QWidget(self)
        filter_layout = QHBoxLayout(filter_container)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(8)

        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)

        filters = [
            ("All", "All Dramas"),
            ("TikTok", "TikTok"),
            ("DramaBox", "DramaBox"),
            ("ReelShort", "ReelShort"),
        ]

        for key, label in filters:
            btn = QPushButton(label, filter_container)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(36)
            if key == "All":
                btn.setChecked(True)
            btn.setStyleSheet(
                f"""
                QPushButton {{
                    background-color: {COLORS.bg_surface};
                    color: {COLORS.text_secondary};
                    border: 1px solid {COLORS.border_subtle};
                    border-radius: 18px;
                    padding: 0 16px;
                    font-size: 12px;
                    font-weight: 600;
                }}
                QPushButton:hover:!checked {{
                    background-color: {COLORS.bg_hover};
                    color: {COLORS.text_primary};
                    border: 1px solid {COLORS.text_muted};
                }}
                QPushButton:checked {{
                    background-color: {COLORS.accent_primary};
                    color: #ffffff;
                    border: 1px solid {COLORS.accent_primary};
                    font-weight: 700;
                }}
                """
            )
            btn.clicked.connect(lambda checked=False, k=key: self._set_platform_filter(k))
            self._filter_group.addButton(btn)
            filter_layout.addWidget(btn)

        toolbar.addWidget(filter_container)
        main_layout.addLayout(toolbar)

        # 2. Drama Cards Grid Area with Lazy Loading Scroll
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("background: transparent;")

        self._grid_container = QWidget(self._scroll)
        self._grid_container.setStyleSheet("background: transparent;")
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(0, 8, 0, 16)
        self._grid_layout.setSpacing(18)
        self._grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._scroll.setWidget(self._grid_container)
        # Connect vertical scroll for infinite scroll detection
        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        main_layout.addWidget(self._scroll, 1)

        # 3. Bottom Footer with Load More & Status Counter
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(12)

        self._status_lbl = QLabel("Ready.", self)
        self._status_lbl.setStyleSheet(f"color: {COLORS.text_muted}; font-size: 12px;")
        footer_layout.addWidget(self._status_lbl, 1)

        self._load_more_btn = QPushButton("Load More Dramas ↓", self)
        self._load_more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._load_more_btn.setStyleSheet(
            f"background-color: {COLORS.bg_surface}; color: {COLORS.text_primary}; border: 1px solid {COLORS.border_subtle}; border-radius: 6px; padding: 6px 14px; font-size: 12px; font-weight: 600;"
        )
        self._load_more_btn.clicked.connect(self._load_next_batch)
        self._load_more_btn.hide()
        footer_layout.addWidget(self._load_more_btn)

        main_layout.addLayout(footer_layout)

    def refresh_catalog(self) -> None:
        """Fetch online drama catalogs in background worker with realtime progressive updates."""
        self._status_lbl.setText("Updating short drama catalog in realtime...")
        self._worker = DramaCatalogWorker(platform_filter="All", parent=self)
        self._worker.catalog_chunk.connect(self._on_catalog_chunk)
        self._worker.catalog_loaded.connect(self._on_catalog_loaded)
        self._worker.error_occurred.connect(self._on_catalog_error)
        self._worker.start()

    def refresh_catalog_if_needed(self) -> None:
        """Trigger background refresh if catalog is currently empty."""
        if not self._all_dramas:
            self.refresh_catalog()

    def _on_catalog_chunk(self, items: List[DramaCatalogItem]) -> None:
        """Handle realtime chunk of dramas as each platform completes."""
        prev_len = len(self._all_dramas)
        self._all_dramas = items
        if prev_len == 0 or len(items) > prev_len:
            self._apply_filter(keep_scroll=True)

    def _on_catalog_loaded(self, items: List[DramaCatalogItem]) -> None:
        self._all_dramas = items
        self._apply_filter(keep_scroll=True)
        self._status_lbl.setText(f"Live catalog updated: {len(self._all_dramas)} dramas available.")

    def _on_catalog_error(self, err_msg: str) -> None:
        self._status_lbl.setText(f"Catalog notice: {err_msg}")

    def _set_platform_filter(self, platform_name: str) -> None:
        self._active_filter = platform_name
        self._apply_filter(keep_scroll=False)

    def _on_search_text_changed(self) -> None:
        self._apply_filter(keep_scroll=False)

    def _apply_filter(self, keep_scroll: bool = False) -> None:
        """Filter dataset by active platform and query text, then update lazy rendering."""
        query = self._search_input.text().strip().lower()

        filtered = []
        for d in self._all_dramas:
            if self._active_filter != "All" and d.platform != self._active_filter:
                continue
            if query:
                in_title = query in d.title.lower()
                in_desc = query in d.description.lower()
                in_tags = any(query in t.lower() for t in d.tags)
                in_url = query in d.url.lower()
                if not (in_title or in_desc or in_tags or in_url):
                    continue
            filtered.append(d)

        self._filtered_dramas = filtered
        if keep_scroll and self._rendered_count > 0:
            total = len(self._filtered_dramas)
            self._status_lbl.setText(
                f"Showing {min(self._rendered_count, total)} of {total} {self._active_filter} short dramas."
            )
            if self._rendered_count < total:
                self._load_more_btn.show()
                self._load_more_btn.setText(f"Load More Dramas ({total - self._rendered_count} remaining) ↓")
            else:
                self._load_more_btn.hide()
            return

        self._reset_grid_and_render_first_batch()

    def _reset_grid_and_render_first_batch(self) -> None:
        """Clear layout widgets and render the initial page batch."""
        # Cancel any pending loaders
        for loader in self._active_loaders:
            if loader.isRunning():
                loader.quit()
        self._active_loaders.clear()

        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self._card_widgets.clear()
        self._rendered_count = 0

        if not self._filtered_dramas:
            empty_lbl = QLabel("No short dramas match your search or filter.", self._grid_container)
            empty_lbl.setStyleSheet(f"color: {COLORS.text_muted}; font-size: 14px; padding: 40px;")
            self._grid_layout.addWidget(empty_lbl, 0, 0)
            self._status_lbl.setText("0 dramas match filter.")
            self._load_more_btn.hide()
            return

        self._load_next_batch()

    def _calculate_columns(self) -> int:
        """Calculate responsive column count based on available viewport width across all devices."""
        vp_w = self._scroll.viewport().width()
        if vp_w <= 0:
            vp_w = self.width() - 40
        # Dynamically scale columns from 1 to 8 based on width
        cols = max(1, (vp_w - 20) // 210)
        return max(1, min(cols, 8))

    def resizeEvent(self, event) -> None:
        """Reflow grid cards responsively whenever the window or device display resizes."""
        super().resizeEvent(event)
        self._relayout_grid_if_needed()

    def _relayout_grid_if_needed(self) -> None:
        """Reposition cards across responsive columns dynamically without losing scroll position."""
        new_cols = self._calculate_columns()
        if new_cols == self._current_cols or not self._card_widgets:
            return
        self._current_cols = new_cols
        self._grid_container.setUpdatesEnabled(False)
        widgets = list(self._card_widgets.values())
        for idx, card in enumerate(widgets):
            row = idx // new_cols
            col = idx % new_cols
            self._grid_layout.addWidget(card, row, col)
        self._grid_container.setUpdatesEnabled(True)

    def _load_next_batch(self) -> None:
        """Lazy load and render the next batch of cards responsively into the grid."""
        total = len(self._filtered_dramas)
        if self._rendered_count >= total:
            self._load_more_btn.hide()
            return

        start = self._rendered_count
        end = min(start + self.BATCH_SIZE, total)
        batch = self._filtered_dramas[start:end]

        cols = self._calculate_columns()
        self._current_cols = cols

        for idx_in_batch, d in enumerate(batch):
            global_idx = start + idx_in_batch
            row = global_idx // cols
            col = global_idx % cols

            card = DramaCardWidget(d, self._grid_container)
            card.preview_clicked.connect(self._open_preview_dialog)

            self._grid_layout.addWidget(card, row, col)
            self._card_widgets[d.id] = card

            # Lazy thumbnail download only if not in memory/disk cache
            if d.cover_url and d.cover_url not in IMAGE_MEMORY_CACHE:
                cached_disk = DramaCatalogService.get_cached_cover_path(d.cover_url)
                if not cached_disk:
                    loader = LazyCoverLoader(d.id, d.cover_url, self)
                    loader.cover_loaded.connect(self._on_cover_loaded)
                    self._active_loaders.append(loader)
                    loader.start()

        self._rendered_count = end

        # Update footer status
        self._status_lbl.setText(
            f"Showing {self._rendered_count} of {total} {self._active_filter} short dramas."
        )
        if self._rendered_count < total:
            remaining = total - self._rendered_count
            self._load_more_btn.setText(f"Load More Dramas ({remaining} remaining) ↓")
            self._load_more_btn.show()
        else:
            self._load_more_btn.hide()

    def _on_scroll_changed(self, value: int) -> None:
        """Trigger infinite-scroll lazy loading when scrollbar approaches bottom."""
        sb = self._scroll.verticalScrollBar()
        if sb.maximum() > 0 and value >= sb.maximum() - 150:
            if self._rendered_count < len(self._filtered_dramas):
                self._load_next_batch()

    def _on_cover_loaded(self, drama_id: str, pixmap: QPixmap) -> None:
        """Handle async cover image arrival."""
        card = self._card_widgets.get(drama_id)
        if card:
            card.set_cover_pixmap(pixmap)

    def _on_search_entered(self) -> None:
        """If user enters full URL, immediately request direct download/analysis."""
        text = self._search_input.text().strip()
        if text.startswith("http://") or text.startswith("https://"):
            self.request_download.emit(text)

    def _open_preview_dialog(self, drama: DramaCatalogItem) -> None:
        """Open detailed preview modal for inspecting episodes and previewing stream."""
        dialog = DramaPreviewDialog(drama=drama, parent=self)
        dialog.download_requested.connect(self.request_download.emit)
        dialog.exec()

    def closeEvent(self, event) -> None:
        """Gracefully stop background catalog and cover loading threads."""
        if hasattr(self, "_worker") and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(800)
        for loader in self._active_loaders:
            if loader.isRunning():
                loader.quit()
                loader.wait(200)
        super().closeEvent(event)
