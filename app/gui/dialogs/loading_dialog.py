"""Modal loading dialog shown while analyzing media URLs."""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.assets import create_vector_icon
from app.gui.styles import COLORS


class MediaLoadingDialog(QDialog):
    """Clean desktop popup displaying an indeterminate progress bar while media is analyzed."""

    def __init__(
        self,
        url: str,
        platform: str = "Video",
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize loading dialog.

        Args:
            url: Media URL being extracted.
            platform: Platform name (e.g. YouTube, TikTok).
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Analyzing Media")
        self.setFixedSize(420, 160)
        self.setModal(True)
        self.setStyleSheet(
            f"QDialog {{ background-color: {COLORS.bg_window}; border: 1px solid {COLORS.border_subtle}; border-radius: 8px; }}"
            f"QLabel {{ background: transparent; color: {COLORS.text_primary}; }}"
        )

        self._init_ui(url=url, platform=platform)

    def _init_ui(self, url: str, platform: str) -> None:
        """Construct popup UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)

        # Header with icon and title
        header_layout = QHBoxLayout()
        header_layout.setSpacing(10)

        icon_label = QLabel(self)
        icon_label.setPixmap(create_vector_icon("downloader", size=20).pixmap(20, 20))
        header_layout.addWidget(icon_label)

        title_label = QLabel("Analyzing Media...", self)
        title_label.setObjectName("dialogTitle")
        title_label.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {COLORS.text_primary};")
        header_layout.addWidget(title_label, 1)

        layout.addLayout(header_layout)

        # Subtitle with platform context
        sub_text = f"Fetching video details and formats from {platform.title()}..."
        subtitle_label = QLabel(sub_text, self)
        subtitle_label.setObjectName("dialogSubtitle")
        subtitle_label.setStyleSheet(f"font-size: 12px; color: {COLORS.text_secondary};")
        layout.addWidget(subtitle_label)

        # Indeterminate animated loading bar
        self._progress_bar = QProgressBar(self)
        self._progress_bar.setRange(0, 0)  # Native indeterminate animated loading mode
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ background-color: {COLORS.bg_surface}; border: none; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background-color: {COLORS.accent_primary}; border-radius: 4px; }}"
        )
        layout.addWidget(self._progress_bar)

        # Action button row (Cancel button)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._cancel_btn = QPushButton("Cancel", self)
        self._cancel_btn.setObjectName("dangerButton")
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        layout.addLayout(btn_layout)
