"""License and product activation page for MediaFlow GUI."""

import logging
from typing import Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.database.database import DatabaseManager
from app.database.repository import SettingsRepository
from app.gui.assets import create_vector_icon
from app.gui.styles import COLORS
from app.services.hardware import get_machine_id
from app.services.license import LicenseInfo, LicenseService, LicenseStatus

logger = logging.getLogger(__name__)


def clean_product_key_input(raw: Optional[str]) -> str:
    """Sanitize and format product key input string.

    Args:
        raw: Raw input string from clipboard or text field.

    Returns:
        Cleaned, uppercase, trimmed license key string.
    """
    if not raw or not isinstance(raw, str):
        return ""
    return raw.strip().upper()


def mask_license_key(key: Optional[str]) -> str:
    """Mask inner segments of a license key to protect sensitive credentials.

    Args:
        key: Full license key string (e.g. MDFL-XXXX-YYYY-ZZZZ-WWWW).

    Returns:
        Masked representation (e.g. MDFL-XXXX-****-****-WWWW) or 'None'.
    """
    if not key or not isinstance(key, str):
        return "None"

    clean = key.strip().upper()
    parts = clean.split("-")
    if len(parts) <= 2:
        return clean

    # Mask intermediate chunks
    masked_chunks = [parts[0], parts[1]]
    for _ in range(2, len(parts) - 1):
        masked_chunks.append("****")
    masked_chunks.append(parts[-1])
    return "-".join(masked_chunks)


def get_license_badge_properties(info: LicenseInfo) -> Tuple[str, str, str]:
    """Derive display text, background color, and text color for license status.

    Args:
        info: LicenseInfo status object.

    Returns:
        Tuple of (display_text, background_color, text_color).
    """
    if info.is_valid and info.status == LicenseStatus.ACTIVE:
        if info.is_lifetime:
            return "Active (Lifetime)", COLORS.status_success_bg, COLORS.status_success
        return f"Active ({info.days_remaining}d remaining)", COLORS.status_success_bg, COLORS.status_success

    if info.status == LicenseStatus.TAMPERED:
        return "Clock Error", COLORS.status_danger_bg, COLORS.status_danger

    if info.status == LicenseStatus.EXPIRED:
        return "Expired", COLORS.status_warning_bg, COLORS.status_warning

    return "Unactivated", COLORS.bg_surface_alt, COLORS.text_secondary


class LicensePage(QWidget):
    """License activation, status monitoring, and key management page."""

    license_updated = Signal(object)

    def __init__(
        self,
        license_service: Optional[LicenseService] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize LicensePage.

        Args:
            license_service: Optional LicenseService instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.license_service = license_service or LicenseService(
            settings_repo=SettingsRepository(db_manager=DatabaseManager())
        )

        self._init_ui()
        self.refresh_status()

    def _init_ui(self) -> None:
        """Construct the License page layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        # Header Title & Subtitle
        header_box = QVBoxLayout()
        header_box.setSpacing(4)

        title_label = QLabel("License & Activation", self)
        title_label.setObjectName("pageTitle")
        header_box.addWidget(title_label)

        desc_label = QLabel(
            "Manage your offline cryptographic license key and machine authorization.",
            self,
        )
        desc_label.setObjectName("secondaryText")
        header_box.addWidget(desc_label)

        layout.addLayout(header_box)
        layout.addWidget(self._create_divider())

        # Section 1: Current License Status
        sec1_header = QLabel("Current License Status", self)
        sec1_header.setObjectName("sectionHeader")
        layout.addWidget(sec1_header)

        # Status Card (Flat 1px border, surface background, no shadow)
        self._status_card = QFrame(self)
        self._status_card.setStyleSheet(
            f"QFrame {{ background-color: {COLORS.bg_surface}; border: 1px solid {COLORS.border_subtle}; "
            f"border-radius: 6px; padding: 14px; }}"
        )
        card_layout = QVBoxLayout(self._status_card)
        card_layout.setSpacing(10)
        card_layout.setContentsMargins(14, 14, 14, 14)

        # Row 1: Status & Tier
        row1 = QHBoxLayout()
        row1.setSpacing(12)

        status_prefix = QLabel("Status:", self._status_card)
        status_prefix.setStyleSheet("font-weight: 500; font-size: 12px; color: " + COLORS.text_secondary)
        row1.addWidget(status_prefix)

        self._status_badge = QLabel("Checking...", self._status_card)
        self._status_badge.setStyleSheet(
            f"padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; "
            f"background-color: {COLORS.bg_surface_alt}; color: {COLORS.text_secondary};"
        )
        row1.addWidget(self._status_badge)

        row1.addSpacing(16)

        tier_prefix = QLabel("Tier:", self._status_card)
        tier_prefix.setStyleSheet("font-weight: 500; font-size: 12px; color: " + COLORS.text_secondary)
        row1.addWidget(tier_prefix)

        self._tier_label = QLabel("--", self._status_card)
        self._tier_label.setStyleSheet("font-weight: 600; font-size: 13px; color: " + COLORS.text_primary)
        row1.addWidget(self._tier_label)

        row1.addStretch()
        card_layout.addLayout(row1)

        # Row 2: Expiration / Validity
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        expiry_prefix = QLabel("Validity:", self._status_card)
        expiry_prefix.setStyleSheet("font-weight: 500; font-size: 12px; color: " + COLORS.text_secondary)
        row2.addWidget(expiry_prefix)

        self._expiry_label = QLabel("--", self._status_card)
        self._expiry_label.setStyleSheet("font-size: 12px; color: " + COLORS.text_primary)
        row2.addWidget(self._expiry_label, 1)

        card_layout.addLayout(row2)

        # Row 3: Active Key (Masked)
        row3 = QHBoxLayout()
        row3.setSpacing(8)

        key_prefix = QLabel("Active Key:", self._status_card)
        key_prefix.setStyleSheet("font-weight: 500; font-size: 12px; color: " + COLORS.text_secondary)
        row3.addWidget(key_prefix)

        self._active_key_label = QLabel("None", self._status_card)
        self._active_key_label.setStyleSheet(
            f"font-family: Consolas, monospace; font-size: 12px; color: {COLORS.text_muted};"
        )
        row3.addWidget(self._active_key_label, 1)

        card_layout.addLayout(row3)

        # Row 4: Machine ID (Hardware Fingerprint)
        row4 = QHBoxLayout()
        row4.setSpacing(8)

        hwid_prefix = QLabel("Machine ID:", self._status_card)
        hwid_prefix.setStyleSheet("font-weight: 500; font-size: 12px; color: " + COLORS.text_secondary)
        row4.addWidget(hwid_prefix)

        self._machine_id = get_machine_id()
        self._hwid_label = QLabel(self._machine_id, self._status_card)
        self._hwid_label.setStyleSheet(
            f"font-family: Consolas, monospace; font-size: 12px; font-weight: 600; color: {COLORS.accent_primary};"
        )
        row4.addWidget(self._hwid_label)

        copy_hwid_btn = QPushButton("Copy ID", self._status_card)
        copy_hwid_btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        copy_hwid_btn.clicked.connect(self._on_copy_hwid)
        row4.addWidget(copy_hwid_btn)

        row4.addStretch()
        card_layout.addLayout(row4)

        layout.addWidget(self._status_card)

        # Clock-Tampering Warning Banner (hidden by default)
        self._tamper_banner = QFrame(self)
        self._tamper_banner.setStyleSheet(
            f"QFrame {{ background-color: {COLORS.status_danger_bg}; border: 1px solid {COLORS.status_danger}; "
            f"border-radius: 6px; padding: 10px; }}"
        )
        tamper_layout = QHBoxLayout(self._tamper_banner)
        tamper_layout.setContentsMargins(12, 8, 12, 8)
        tamper_text = QLabel(
            "System clock rollback detected. The local system time is earlier than the last verified check. "
            "Please restore your computer date and time to continue using MediaFlow.",
            self._tamper_banner,
        )
        tamper_text.setStyleSheet(f"color: {COLORS.text_primary}; font-size: 12px; font-weight: 500;")
        tamper_layout.addWidget(tamper_text)
        self._tamper_banner.hide()
        layout.addWidget(self._tamper_banner)

        layout.addWidget(self._create_divider())

        # Section 2: Activate Product Key
        sec2_header = QLabel("Activate Product Key", self)
        sec2_header.setObjectName("sectionHeader")
        layout.addWidget(sec2_header)

        key_input_row = QHBoxLayout()
        key_input_row.setSpacing(8)

        self._key_input = QLineEdit(self)
        self._key_input.setPlaceholderText("MDFL-XXXXX-XXXXX-XXXXX-...")
        self._key_input.setStyleSheet(f"QLineEdit {{ font-family: Consolas, monospace; font-size: 13px; }}")
        self._key_input.textChanged.connect(self._clear_error)
        key_input_row.addWidget(self._key_input, 1)

        paste_btn = QPushButton("Paste Key", self)
        paste_btn.clicked.connect(self._on_paste_key)
        key_input_row.addWidget(paste_btn)

        layout.addLayout(key_input_row)

        # Inline Error Label (Strictly placed directly beneath input field)
        self._key_error_label = QLabel(self)
        self._key_error_label.setStyleSheet(f"color: {COLORS.status_danger}; font-size: 11px;")
        self._key_error_label.hide()
        layout.addWidget(self._key_error_label)

        # Action Buttons Row
        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)

        activate_btn = QPushButton("Activate License", self)
        activate_btn.setObjectName("primaryButton")
        activate_btn.clicked.connect(self._on_activate_clicked)
        actions_row.addWidget(activate_btn)

        self._deactivate_btn = QPushButton("Deactivate Key", self)
        self._deactivate_btn.setObjectName("dangerButton")
        self._deactivate_btn.clicked.connect(self._on_deactivate_clicked)
        actions_row.addWidget(self._deactivate_btn)

        self._action_status_label = QLabel(self)
        self._action_status_label.setStyleSheet(f"color: {COLORS.status_success}; font-size: 12px; font-weight: 500;")
        self._action_status_label.hide()
        actions_row.addWidget(self._action_status_label)

        actions_row.addStretch()
        layout.addLayout(actions_row)

        layout.addWidget(self._create_divider())

        # Section 3: Feature Capabilities
        features_header = QLabel("Tier Capabilities", self)
        features_header.setObjectName("sectionHeader")
        layout.addWidget(features_header)

        features_info = QLabel(
            "Free Mode: Up to 3 concurrent downloads and standard extraction.\n"
            "Pro & Lifetime Tiers: Up to 20 concurrent downloads, batch drama episode downloads, "
            "and automated high-resolution video/audio muxing.",
            self,
        )
        features_info.setObjectName("captionText")
        layout.addWidget(features_info)

        layout.addStretch(1)

    def _create_divider(self) -> QFrame:
        """Create a flat 1px subtle divider line."""
        line = QFrame(self)
        line.setObjectName("dividerLine")
        line.setFrameShape(QFrame.Shape.HLine)
        return line

    def refresh_status(self) -> LicenseInfo:
        """Query current license from service and update UI controls.

        Returns:
            Active LicenseInfo object.
        """
        info = self.license_service.get_current_license()

        # Update Status Badge
        badge_text, bg_color, text_color = get_license_badge_properties(info)
        self._status_badge.setText(badge_text)
        self._status_badge.setStyleSheet(
            f"padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; "
            f"background-color: {bg_color}; color: {text_color};"
        )

        # Update Tier
        if info.is_valid:
            tier_display = "Lifetime" if info.is_lifetime else info.tier.upper()
        else:
            tier_display = "Unactivated"
        self._tier_label.setText(tier_display)

        # Update Expiration / Validity
        if info.is_valid:
            if info.is_lifetime:
                self._expiry_label.setText("Permanent Lifetime License (Unlimited)")
            else:
                self._expiry_label.setText(
                    f"{info.days_remaining} days remaining (Expires: {info.expires_at})"
                )
        elif info.status == LicenseStatus.EXPIRED:
            self._expiry_label.setText(f"Expired on {info.expires_at}. Please renew your key.")
        elif info.status == LicenseStatus.TAMPERED:
            self._expiry_label.setText("Suspended: System clock mismatch.")
        else:
            self._expiry_label.setText("Unactivated. Enter a valid product key to unlock full features.")

        # Update Masked Key
        self._active_key_label.setText(mask_license_key(info.license_key))

        # Show/Hide Clock Tamper Banner
        self._tamper_banner.setVisible(info.status == LicenseStatus.TAMPERED)

        # Toggle Deactivate button
        self._deactivate_btn.setEnabled(info.is_valid)

        return info

    def _on_paste_key(self) -> None:
        """Paste clipboard content into product key input."""
        clipboard_text = QApplication.clipboard().text()
        cleaned = clean_product_key_input(clipboard_text)
        if cleaned:
            self._key_input.setText(cleaned)
            self._clear_error()

    def _on_copy_hwid(self) -> None:
        """Copy hardware Machine ID to system clipboard."""
        clipboard = QApplication.clipboard()
        clipboard.setText(self._machine_id)
        self._action_status_label.setStyleSheet(f"color: {COLORS.text_secondary}; font-size: 12px; font-weight: 500;")
        self._action_status_label.setText("Machine ID copied to clipboard.")
        self._action_status_label.show()

    def _on_activate_clicked(self) -> None:
        """Validate and activate the entered license key."""
        raw_key = clean_product_key_input(self._key_input.text())
        if not raw_key:
            self._key_error_label.setText("Please enter a license key.")
            self._key_error_label.show()
            return

        info = self.license_service.activate(raw_key)

        if not info.is_valid:
            # Inline error display
            self._key_error_label.setText(info.message or "Invalid product key.")
            self._key_error_label.show()
            self._action_status_label.hide()
            return

        self._clear_error()
        self._key_input.clear()
        self.refresh_status()

        self._action_status_label.setStyleSheet(f"color: {COLORS.status_success}; font-size: 12px; font-weight: 500;")
        self._action_status_label.setText("License activated successfully.")
        self._action_status_label.show()

        self.license_updated.emit(info)

    def _on_deactivate_clicked(self) -> None:
        """Confirm and deactivate the active license."""
        reply = QMessageBox.question(
            self,
            "Deactivate License",
            "Are you sure you want to deactivate your license on this computer?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.license_service.deactivate()
            info = self.refresh_status()

            self._action_status_label.setStyleSheet(f"color: {COLORS.text_secondary}; font-size: 12px; font-weight: 500;")
            self._action_status_label.setText("License deactivated.")
            self._action_status_label.show()

            self.license_updated.emit(info)

    def _clear_error(self) -> None:
        """Hide inline error label."""
        self._key_error_label.hide()
        self._key_error_label.setText("")
