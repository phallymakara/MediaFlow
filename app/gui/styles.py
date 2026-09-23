"""Centralized visual styles, color tokens, and stylesheets for MediaFlow."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeColors:
    """Color palette tokens for the dark slate desktop theme."""

    bg_window: str = "#18181b"
    bg_surface: str = "#1f1f23"
    bg_surface_alt: str = "#1b1b1f"
    bg_input: str = "#222227"
    bg_hover: str = "#27272a"
    bg_selected: str = "#2f2f36"

    border_subtle: str = "#2e2e33"
    border_focus: str = "#2563eb"
    border_error: str = "#dc2626"

    accent_primary: str = "#2563eb"
    accent_hover: str = "#1d4ed8"
    accent_pressed: str = "#1e40af"

    status_success: str = "#16a34a"
    status_success_bg: str = "#14532d"
    status_danger: str = "#dc2626"
    status_danger_bg: str = "#7f1d1d"
    status_warning: str = "#d97706"
    status_warning_bg: str = "#78350f"
    status_info: str = "#2563eb"
    status_info_bg: str = "#1e3a8a"

    text_primary: str = "#f4f4f5"
    text_secondary: str = "#a1a1aa"
    text_muted: str = "#71717a"
    text_disabled: str = "#52525b"


COLORS = ThemeColors()

FONT_FAMILY = '"Segoe UI", "SF Pro Display", "Inter", sans-serif'


def get_application_stylesheet() -> str:
    """Return the complete application-level QSS stylesheet.

    Enforces flat borders, crisp typography, dark slate backgrounds,
    and zero drop shadows across all native Qt widgets.
    """
    return f"""
    /* Global Application Styles */
    QMainWindow, QWidget {{
        background-color: {COLORS.bg_window};
        color: {COLORS.text_primary};
        font-family: {FONT_FAMILY};
        font-size: 13px;
    }}

    /* Splitters and Frames */
    QFrame#sidebarFrame {{
        background-color: {COLORS.bg_surface};
        border-right: 1px solid {COLORS.border_subtle};
    }}

    QFrame#contentFrame {{
        background-color: {COLORS.bg_window};
    }}

    QFrame#dividerLine {{
        background-color: {COLORS.border_subtle};
        max-height: 1px;
        border: none;
    }}

    /* Typography Labels */
    QLabel {{
        color: {COLORS.text_primary};
        background: transparent;
    }}

    QLabel#pageTitle {{
        font-size: 17px;
        font-weight: 600;
        color: {COLORS.text_primary};
    }}

    QLabel#sectionHeader {{
        font-size: 12px;
        font-weight: 600;
        text-transform: uppercase;
        color: {COLORS.text_muted};
        letter-spacing: 0.5px;
    }}

    QLabel#secondaryText {{
        font-size: 12px;
        color: {COLORS.text_secondary};
    }}

    QLabel#captionText {{
        font-size: 11px;
        color: {COLORS.text_muted};
    }}

    QLabel#errorText {{
        font-size: 12px;
        color: {COLORS.border_error};
    }}

    /* Input Fields */
    QLineEdit {{
        background-color: {COLORS.bg_input};
        border: 1px solid {COLORS.border_subtle};
        border-radius: 6px;
        padding: 7px 12px;
        color: {COLORS.text_primary};
        font-size: 13px;
        selection-background-color: {COLORS.accent_primary};
        selection-color: #ffffff;
    }}

    QLineEdit:focus {{
        border: 1px solid {COLORS.border_focus};
    }}

    QLineEdit:disabled {{
        background-color: {COLORS.bg_surface};
        color: {COLORS.text_disabled};
        border-color: {COLORS.border_subtle};
    }}

    QLineEdit#inputError {{
        border: 1px solid {COLORS.border_error};
    }}

    /* ComboBox Dropdowns */
    QComboBox {{
        background-color: {COLORS.bg_input};
        border: 1px solid {COLORS.border_subtle};
        border-radius: 6px;
        padding: 7px 12px;
        color: {COLORS.text_primary};
        font-size: 13px;
        min-width: 120px;
    }}

    QComboBox:focus, QComboBox:hover {{
        border: 1px solid {COLORS.border_focus};
    }}

    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 26px;
        border-left: none;
    }}

    QComboBox QAbstractItemView {{
        background-color: {COLORS.bg_surface};
        border: 1px solid {COLORS.border_subtle};
        color: {COLORS.text_primary};
        selection-background-color: {COLORS.bg_selected};
        selection-color: {COLORS.text_primary};
        padding: 4px;
        outline: none;
    }}

    /* Buttons */
    QPushButton {{
        background-color: {COLORS.bg_input};
        border: 1px solid {COLORS.border_subtle};
        border-radius: 6px;
        padding: 7px 16px;
        color: {COLORS.text_primary};
        font-size: 13px;
        font-weight: 500;
    }}

    QPushButton:hover {{
        background-color: {COLORS.bg_hover};
        border-color: {COLORS.text_muted};
    }}

    QPushButton:pressed {{
        background-color: {COLORS.bg_selected};
    }}

    QPushButton:disabled {{
        background-color: {COLORS.bg_surface};
        color: {COLORS.text_disabled};
        border-color: {COLORS.border_subtle};
    }}

    /* Primary Filled Button */
    QPushButton#primaryButton {{
        background-color: {COLORS.accent_primary};
        border: 1px solid {COLORS.accent_primary};
        color: #ffffff;
        font-weight: 600;
    }}

    QPushButton#primaryButton:hover {{
        background-color: {COLORS.accent_hover};
        border-color: {COLORS.accent_hover};
    }}

    QPushButton#primaryButton:pressed {{
        background-color: {COLORS.accent_pressed};
    }}

    /* Danger / Cancel Button */
    QPushButton#dangerButton {{
        background-color: transparent;
        border: 1px solid {COLORS.status_danger};
        color: {COLORS.status_danger};
        padding: 4px 10px;
        font-size: 12px;
    }}

    QPushButton#dangerButton:hover {{
        background-color: {COLORS.status_danger};
        color: #ffffff;
    }}

    /* Compact Table Action Buttons */
    QPushButton#rowActionButton {{
        background-color: transparent;
        border: 1px solid {COLORS.border_subtle};
        border-radius: 4px;
        padding: 4px 8px;
        font-size: 11px;
        color: {COLORS.text_secondary};
    }}

    QPushButton#rowActionButton:hover {{
        background-color: {COLORS.bg_hover};
        border-color: {COLORS.text_muted};
        color: {COLORS.text_primary};
    }}

    /* Sidebar Navigation Buttons */
    QPushButton#navButton {{
        background-color: transparent;
        border: none;
        border-radius: 6px;
        padding: 10px 14px;
        color: {COLORS.text_secondary};
        font-size: 13px;
        font-weight: 500;
        text-align: left;
    }}

    QPushButton#navButton:hover {{
        background-color: {COLORS.bg_hover};
        color: {COLORS.text_primary};
    }}

    QPushButton#navButtonActive {{
        background-color: {COLORS.bg_selected};
        border-left: 3px solid {COLORS.accent_primary};
        border-radius: 4px;
        padding: 10px 14px;
        color: {COLORS.text_primary};
        font-size: 13px;
        font-weight: 600;
        text-align: left;
    }}

    /* Tabular Task Queue (QTableWidget) */
    QTableWidget {{
        background-color: {COLORS.bg_window};
        border: none;
        gridline-color: transparent;
        selection-background-color: {COLORS.bg_selected};
        selection-color: {COLORS.text_primary};
        outline: none;
    }}

    QTableWidget::item {{
        padding: 6px 10px;
        border-bottom: 1px solid {COLORS.bg_surface};
    }}

    QTableWidget::item:selected {{
        background-color: {COLORS.bg_selected};
    }}

    QHeaderView::section {{
        background-color: {COLORS.bg_surface};
        color: {COLORS.text_muted};
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        padding: 8px 10px;
        border: none;
        border-bottom: 1px solid {COLORS.border_subtle};
    }}

    /* Slim Progress Bar */
    QProgressBar {{
        background-color: {COLORS.border_subtle};
        border: none;
        border-radius: 3px;
        max-height: 6px;
        min-height: 6px;
        text-align: right;
    }}

    QProgressBar::chunk {{
        background-color: {COLORS.accent_primary};
        border-radius: 3px;
    }}

    QProgressBar#progressCompleted::chunk {{
        background-color: {COLORS.status_success};
    }}

    /* Scrollbars */
    QScrollBar:vertical {{
        background: {COLORS.bg_window};
        width: 8px;
        margin: 0px;
    }}

    QScrollBar::handle:vertical {{
        background: {COLORS.border_subtle};
        min-height: 24px;
        border-radius: 4px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {COLORS.text_muted};
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QScrollBar:horizontal {{
        background: {COLORS.bg_window};
        height: 8px;
        margin: 0px;
    }}

    QScrollBar::handle:horizontal {{
        background: {COLORS.border_subtle};
        min-width: 24px;
        border-radius: 4px;
    }}

    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}

    /* Sliders and Spinboxes */
    QSlider::groove:horizontal {{
        height: 6px;
        background: {COLORS.border_subtle};
        border-radius: 3px;
    }}

    QSlider::sub-page:horizontal {{
        background: {COLORS.accent_primary};
        border-radius: 3px;
    }}

    QSlider::handle:horizontal {{
        background: #ffffff;
        border: 1px solid {COLORS.accent_primary};
        width: 14px;
        margin-top: -4px;
        margin-bottom: -4px;
        border-radius: 7px;
    }}

    QSpinBox {{
        background-color: {COLORS.bg_input};
        border: 1px solid {COLORS.border_subtle};
        border-radius: 6px;
        padding: 5px 8px;
        color: {COLORS.text_primary};
    }}

    QSpinBox:focus {{
        border: 1px solid {COLORS.border_focus};
    }}
    """
