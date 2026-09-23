"""Global navigation sidebar component for MediaFlow GUI."""

from dataclasses import dataclass
from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.gui.assets import create_vector_icon, get_logo_pixmap
from app.gui.styles import COLORS
from app.services.license import LicenseInfo, LicenseStatus


class ClickableLicenseWidget(QFrame):
    """Bottom sidebar license badge widget that emits click signal."""

    clicked = Signal()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse press event."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


@dataclass(frozen=True)
class SidebarLicenseDisplay:
    """Formatted text and color for the sidebar license indicator."""

    title: str
    subtitle: str
    title_color: str


def format_sidebar_license(info: LicenseInfo) -> SidebarLicenseDisplay:
    """Format license information into title, subtitle, and color tokens.

    Args:
        info: LicenseInfo dataclass.

    Returns:
        SidebarLicenseDisplay with formatted strings and theme color.
    """
    if info.is_valid and info.status == LicenseStatus.ACTIVE:
        if info.is_lifetime:
            return SidebarLicenseDisplay(
                title="LIFETIME TIER",
                subtitle="Permanent License",
                title_color=COLORS.status_success,
            )
        return SidebarLicenseDisplay(
            title=f"{info.tier.upper()} TIER",
            subtitle=f"{info.days_remaining} Days Remaining",
            title_color=COLORS.status_success,
        )

    if info.status == LicenseStatus.TAMPERED:
        return SidebarLicenseDisplay(
            title="CLOCK ERROR",
            subtitle="Rollback Detected",
            title_color=COLORS.status_danger,
        )

    if info.status == LicenseStatus.EXPIRED:
        return SidebarLicenseDisplay(
            title="EXPIRED",
            subtitle="Please Renew Key",
            title_color=COLORS.status_warning,
        )

    return SidebarLicenseDisplay(
        title="FREE MODE",
        subtitle="Unactivated",
        title_color=COLORS.text_secondary,
    )


class Sidebar(QFrame):
    """Fixed-width navigation sidebar hosting branding, navigation buttons, and license status."""

    page_changed = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Initialize navigation sidebar.

        Args:
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setObjectName("sidebarFrame")
        self.setFixedWidth(220)

        self._active_index = 0
        self._nav_buttons: Dict[int, QPushButton] = {}

        self._init_ui()

    def _init_ui(self) -> None:
        """Construct the sidebar layout and internal components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 1. Top Branding Header
        header_widget = QWidget(self)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(18, 18, 18, 18)
        header_layout.setSpacing(12)

        logo_label = QLabel(header_widget)
        logo_label.setPixmap(get_logo_pixmap(28))
        logo_label.setFixedSize(28, 28)
        header_layout.addWidget(logo_label)

        title_label = QLabel("MediaFlow", header_widget)
        title_label.setObjectName("pageTitle")
        title_label.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {COLORS.text_primary};")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        main_layout.addWidget(header_widget)

        # Header divider line
        divider = QFrame(self)
        divider.setObjectName("dividerLine")
        divider.setFixedHeight(1)
        main_layout.addWidget(divider)

        # 2. Middle Navigation Section
        nav_container = QWidget(self)
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(12, 16, 12, 16)
        nav_layout.setSpacing(6)

        nav_items = [
            (0, "Downloader", "downloader"),
            (1, "History", "history"),
            (2, "Settings", "settings"),
            (3, "License", "license"),
        ]

        for index, label, icon_name in nav_items:
            btn = QPushButton(label, nav_container)
            btn.setIcon(create_vector_icon(icon_name, size=18))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, idx=index: self._on_nav_clicked(idx))
            nav_layout.addWidget(btn)
            self._nav_buttons[index] = btn

        nav_layout.addStretch()
        main_layout.addWidget(nav_container, 1)

        # Bottom divider line
        bottom_divider = QFrame(self)
        bottom_divider.setObjectName("dividerLine")
        bottom_divider.setFixedHeight(1)
        main_layout.addWidget(bottom_divider)

        # 3. Bottom License Status Card
        self._license_widget = ClickableLicenseWidget(self)
        self._license_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        self._license_widget.setStyleSheet(
            f"""
            QFrame {{
                background-color: {COLORS.bg_surface};
                border: none;
                padding: 4px;
            }}
            QFrame:hover {{
                background-color: {COLORS.bg_hover};
            }}
            """
        )
        self._license_widget.clicked.connect(lambda: self._on_nav_clicked(3))

        license_layout = QHBoxLayout(self._license_widget)
        license_layout.setContentsMargins(14, 12, 14, 12)
        license_layout.setSpacing(10)

        license_icon = QLabel(self._license_widget)
        license_icon.setPixmap(create_vector_icon("license", color=COLORS.status_success, size=20).pixmap(20, 20))
        license_layout.addWidget(license_icon)

        text_container = QVBoxLayout()
        text_container.setContentsMargins(0, 0, 0, 0)
        text_container.setSpacing(2)

        self._license_title = QLabel("FREE MODE", self._license_widget)
        self._license_title.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {COLORS.text_secondary};")
        text_container.addWidget(self._license_title)

        self._license_subtitle = QLabel("Unactivated", self._license_widget)
        self._license_subtitle.setStyleSheet(f"font-size: 11px; color: {COLORS.text_muted};")
        text_container.addWidget(self._license_subtitle)

        license_layout.addLayout(text_container)
        license_layout.addStretch()

        main_layout.addWidget(self._license_widget)

        # Set default active selection (Downloader)
        self.set_active_page(0)

    def _on_nav_clicked(self, index: int) -> None:
        """Handle button click and emit page changed signal."""
        if index != self._active_index:
            self.set_active_page(index)
            self.page_changed.emit(index)

    def set_active_page(self, index: int) -> None:
        """Update visual button highlight for current active page index.

        Args:
            index: Target page index (0: Downloader, 1: History, 2: Settings, 3: License).
        """
        self._active_index = index

        for idx, btn in self._nav_buttons.items():
            if idx == index:
                btn.setObjectName("navButtonActive")
            else:
                btn.setObjectName("navButton")
            # Refresh stylesheet state
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def update_license_display(self, info: LicenseInfo) -> None:
        """Update bottom license status widget according to current runtime info.

        Args:
            info: Verified LicenseInfo dataclass.
        """
        display = format_sidebar_license(info)
        self._license_title.setText(display.title)
        self._license_title.setStyleSheet(f"font-size: 11px; font-weight: 700; color: {display.title_color};")
        self._license_subtitle.setText(display.subtitle)
