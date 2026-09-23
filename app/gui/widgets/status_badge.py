"""Reusable flat status badge widget for task and item states."""

from dataclasses import dataclass
from typing import Optional, Union

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from app.database.models import DownloadStatus
from app.gui.styles import COLORS


@dataclass(frozen=True)
class StatusBadgeStyle:
    """Style attributes and display label for a status badge."""

    text: str
    bg_color: str
    border_color: str
    text_color: str


def get_status_badge_style(
    status: Union[DownloadStatus, str],
    custom_text: Optional[str] = None,
) -> StatusBadgeStyle:
    """Resolve color attributes and display text for a given status.

    Args:
        status: DownloadStatus enum or raw string.
        custom_text: Optional text override.

    Returns:
        StatusBadgeStyle with text and hex color tokens.
    """
    status_key = status.value if isinstance(status, DownloadStatus) else str(status).lower()

    if status_key == DownloadStatus.DOWNLOADING.value:
        bg_color = COLORS.status_info_bg
        border_color = COLORS.status_info
        text_color = "#93c5fd"
        default_text = "DOWNLOADING"
    elif status_key == DownloadStatus.COMPLETED.value:
        bg_color = COLORS.status_success_bg
        border_color = COLORS.status_success
        text_color = "#86efac"
        default_text = "COMPLETED"
    elif status_key == DownloadStatus.PROCESSING.value:
        bg_color = COLORS.status_warning_bg
        border_color = COLORS.status_warning
        text_color = "#fde047"
        default_text = "PROCESSING"
    elif status_key == DownloadStatus.FAILED.value:
        bg_color = COLORS.status_danger_bg
        border_color = COLORS.status_danger
        text_color = "#fca5a5"
        default_text = "FAILED"
    elif status_key == DownloadStatus.CANCELLED.value:
        bg_color = COLORS.bg_surface
        border_color = COLORS.border_subtle
        text_color = COLORS.text_muted
        default_text = "CANCELLED"
    else:  # QUEUED or default
        bg_color = COLORS.bg_surface
        border_color = COLORS.border_subtle
        text_color = COLORS.text_secondary
        default_text = "QUEUED"

    return StatusBadgeStyle(
        text=custom_text or default_text,
        bg_color=bg_color,
        border_color=border_color,
        text_color=text_color,
    )


class StatusBadge(QFrame):
    """Compact, flat status pill widget without heavy shadows or bloated containers."""

    def __init__(
        self,
        status: Optional[Union[DownloadStatus, str]] = None,
        custom_text: Optional[str] = None,
        parent: Optional[QFrame] = None,
    ) -> None:
        """Initialize status badge widget.

        Args:
            status: Initial status enum or string label.
            custom_text: Optional text override.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setFixedHeight(22)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 0, 8, 0)
        self._layout.setSpacing(0)

        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._label)

        if status:
            self.set_status(status, custom_text)
        else:
            self.set_status(DownloadStatus.QUEUED, custom_text)

    def set_status(
        self,
        status: Union[DownloadStatus, str],
        custom_text: Optional[str] = None,
    ) -> None:
        """Update badge appearance and text according to status.

        Args:
            status: Target DownloadStatus enum or raw string name.
            custom_text: Optional display label override.
        """
        style = get_status_badge_style(status, custom_text)
        self._label.setText(style.text)

        # Flat pill styling with 1px border and no box-shadow
        self.setStyleSheet(
            f"""
            QFrame {{
                background-color: {style.bg_color};
                border: 1px solid {style.border_color};
                border-radius: 11px;
            }}
            QLabel {{
                color: {style.text_color};
                font-size: 11px;
                font-weight: 600;
                letter-spacing: 0.5px;
                background: transparent;
                border: none;
            }}
            """
        )

    def text(self) -> str:
        """Return the current badge text."""
        return self._label.text()
