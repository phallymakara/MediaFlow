"""Episode selection dialog for multi-episode short drama series."""

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.media import MediaEpisode, MediaInfo
from app.gui.styles import COLORS


class EpisodePickerDialog(QDialog):
    """Dialog allowing users to select specific episodes from a drama series to download."""

    def __init__(
        self,
        media_info: MediaInfo,
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize episode picker dialog.

        Args:
            media_info: Extracted drama metadata with episode list.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Select Episodes to Download")
        self.setMinimumSize(480, 520)
        self.setStyleSheet(f"background-color: {COLORS.bg_window}; color: {COLORS.text_primary};")

        self.media_info = media_info
        self._checkboxes: List[QCheckBox] = []

        self._init_ui()

    def _init_ui(self) -> None:
        """Construct dialog components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # 1. Header Information
        header_title = QLabel(self.media_info.title, self)
        header_title.setObjectName("pageTitle")
        header_title.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {COLORS.text_primary};")
        layout.addWidget(header_title)

        count_text = f"Total Episodes Available: {len(self.media_info.episodes)}"
        header_sub = QLabel(count_text, self)
        header_sub.setObjectName("secondaryText")
        layout.addWidget(header_sub)

        # 2. Format Selection & Quick Toggles
        format_layout = QHBoxLayout()
        format_layout.setSpacing(10)

        format_label = QLabel("Quality Format:", self)
        format_layout.addWidget(format_label)

        self._format_combo = QComboBox(self)
        self._format_combo.addItems(["1080p MP4", "720p MP4", "480p MP4", "Audio Only MP3"])
        format_layout.addWidget(self._format_combo)
        format_layout.addStretch()

        layout.addLayout(format_layout)

        # Selection Action Bar
        action_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All", self)
        select_all_btn.clicked.connect(self._select_all)
        action_layout.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("Deselect All", self)
        deselect_all_btn.clicked.connect(self._deselect_all)
        action_layout.addWidget(deselect_all_btn)

        has_full_series = any(ep.episode_number == 0 or "[Full Series Complete]" in ep.title for ep in self.media_info.episodes)
        if has_full_series:
            full_series_btn = QPushButton("Full Series Only", self)
            full_series_btn.setToolTip("Select only the complete series movie compilation")
            full_series_btn.clicked.connect(self._select_full_series_only)
            action_layout.addWidget(full_series_btn)

            episodes_only_btn = QPushButton("Episodes Only", self)
            episodes_only_btn.setToolTip("Select all individual separate episode videos")
            episodes_only_btn.clicked.connect(self._select_episodes_only)
            action_layout.addWidget(episodes_only_btn)

        action_layout.addStretch()
        layout.addLayout(action_layout)

        # 3. Scrollable Episode Checklist
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(
            f"QScrollArea {{ border: 1px solid {COLORS.border_subtle}; background-color: {COLORS.bg_surface}; border-radius: 6px; }}"
        )

        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(12, 12, 12, 12)
        scroll_layout.setSpacing(8)

        from app.extractors.drama_base import BaseDramaExtractor
        clean_drama = BaseDramaExtractor.clean_drama_title(self.media_info.title)

        for ep in self.media_info.episodes:
            if ep.episode_number == 0 or "[Full Series Complete]" in ep.title:
                cb = QCheckBox(f"{ep.title}", scroll_widget)
                cb.setStyleSheet(f"font-weight: 700; color: {COLORS.accent_primary}; font-size: 13px;")
                cb.setToolTip("Complete series compilation containing all episodes in one video file.")
            else:
                clean_ep = (ep.title or "").strip()
                if clean_ep.lower().startswith(clean_drama.lower()):
                    clean_ep = clean_ep[len(clean_drama):].lstrip(" -:_")
                if clean_ep and not clean_ep.lower().startswith("episode") and clean_ep != f"Ep {ep.episode_number}":
                    cb = QCheckBox(f"Episode {ep.episode_number}: {clean_ep}", scroll_widget)
                else:
                    cb = QCheckBox(f"Episode {ep.episode_number}", scroll_widget)
            cb.setChecked(True)  # Default all selected
            cb.setProperty("episode_data", ep)
            cb.toggled.connect(self._update_summary)
            self._checkboxes.append(cb)
            scroll_layout.addWidget(cb)

        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area, 1)

        # 4. Summary & Action Buttons
        self._summary_label = QLabel(self)
        self._summary_label.setObjectName("secondaryText")
        layout.addWidget(self._summary_label)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        self._queue_btn = QPushButton("Queue Selected", self)
        self._queue_btn.setObjectName("primaryButton")
        self._queue_btn.clicked.connect(self.accept)
        button_layout.addWidget(self._queue_btn)

        layout.addLayout(button_layout)

        self._update_summary()

    def _select_all(self) -> None:
        """Select all episode checkboxes."""
        for cb in self._checkboxes:
            cb.setChecked(True)

    def _deselect_all(self) -> None:
        """Deselect all episode checkboxes."""
        for cb in self._checkboxes:
            cb.setChecked(False)

    def _select_full_series_only(self) -> None:
        """Select only the full series compilation."""
        for cb in self._checkboxes:
            ep: MediaEpisode = cb.property("episode_data")
            is_compilation = ep.episode_number == 0 or "[Full Series Complete]" in ep.title
            cb.setChecked(is_compilation)

    def _select_episodes_only(self) -> None:
        """Select only individual separate episode rows."""
        for cb in self._checkboxes:
            ep: MediaEpisode = cb.property("episode_data")
            is_compilation = ep.episode_number == 0 or "[Full Series Complete]" in ep.title
            cb.setChecked(not is_compilation)


    def _update_summary(self) -> None:
        """Update selected count label and toggle queue button state."""
        selected_count = sum(1 for cb in self._checkboxes if cb.isChecked())
        self._summary_label.setText(f"Selected: {selected_count} of {len(self._checkboxes)} episodes")
        self._queue_btn.setEnabled(selected_count > 0)
        self._queue_btn.setText(f"Queue Selected ({selected_count})")

    def get_selected_episodes(self) -> List[MediaEpisode]:
        """Return list of selected MediaEpisode items."""
        return [cb.property("episode_data") for cb in self._checkboxes if cb.isChecked()]

    def get_selected_format(self) -> str:
        """Return the chosen quality format string."""
        return self._format_combo.currentText()
