"""Settings and application configuration page for MediaFlow GUI."""

import logging
import os
from pathlib import Path
import shutil
from typing import Any, Dict, Optional, Tuple

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config import get_config
from app.core.downloader import Downloader
from app.database.database import DatabaseManager
from app.database.repository import SettingsRepository
from app.gui.assets import create_vector_icon
from app.gui.styles import COLORS

logger = logging.getLogger(__name__)

KEY_DOWNLOAD_DIR = "download_dir"
KEY_MAX_CONCURRENT = "max_concurrent_downloads"
KEY_FFMPEG_PATH = "ffmpeg_path"
KEY_COOKIES_FILE = "cookies_file"
KEY_COOKIES_BROWSER = "cookies_browser"


def validate_cookies_file(cookies_path: Optional[str]) -> Tuple[bool, str]:
    """Validate optional Netscape cookies.txt file path.

    Args:
        cookies_path: Path string to test, or None/empty.

    Returns:
        Tuple of (is_valid, error_or_resolved_path).
    """
    if not cookies_path or not cookies_path.strip():
        return True, ""

    try:
        p = Path(cookies_path.strip()).expanduser().resolve()
        if not p.exists():
            return False, f"Cookies file not found: {p}"
        if not p.is_file():
            return False, f"Target path is a directory, not a file: {p}"

        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            f.read(512)

        return True, str(p)
    except Exception as exc:
        return False, f"Cannot read cookies file: {exc}"


def clamp_concurrency(val: Any) -> int:
    """Clamp an arbitrary integer or string to a valid concurrency range (1 to 20).

    Args:
        val: Input concurrency value.

    Returns:
        Integer between 1 and 20 inclusive.
    """
    try:
        numeric = int(val)
        return max(1, min(numeric, 20))
    except (ValueError, TypeError):
        return 3


def validate_download_directory(dir_path: Optional[str]) -> Tuple[bool, str]:
    """Verify that a directory path is non-empty, resolvable, and writable.

    Args:
        dir_path: Path string to test.

    Returns:
        Tuple of (is_valid, error_or_resolved_path).
    """
    if not dir_path or not dir_path.strip():
        return False, "Directory path cannot be empty."

    try:
        p = Path(dir_path.strip()).resolve()

        # If directory does not exist, try to create it to verify permissions
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)

        if not p.is_dir():
            return False, f"Target path is a file, not a directory: {p}"

        # Test write permission
        test_file = p / f".mediaflow_perm_test_{os.getpid()}"
        try:
            test_file.touch(exist_ok=True)
            test_file.unlink(missing_ok=True)
        except OSError:
            return False, f"Directory is not writable: {p}"

        return True, str(p)
    except Exception as exc:
        return False, f"Invalid directory path: {exc}"


def resolve_ffmpeg_status(custom_path: Optional[str] = None) -> Tuple[bool, str]:
    """Determine whether FFmpeg is available and describe its location.

    Args:
        custom_path: Optional custom executable path.

    Returns:
        Tuple of (is_available, description_message).
    """
    if custom_path and custom_path.strip():
        candidate = Path(custom_path.strip()).resolve()
        if candidate.is_file():
            return True, f"Custom executable located: {candidate}"
        return False, "Specified custom binary was not found or is not a valid file."

    # Fall back to system PATH
    system_path = shutil.which("ffmpeg")
    if system_path:
        return True, f"Detected on system PATH: {system_path}"

    return False, "FFmpeg not detected. 1080p+ stream muxing will be disabled."


class SettingsPage(QWidget):
    """Application preferences and configuration management page."""

    settings_saved = Signal(dict)

    def __init__(
        self,
        repository: Optional[SettingsRepository] = None,
        downloader: Optional[Downloader] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize SettingsPage.

        Args:
            repository: Optional SettingsRepository instance.
            downloader: Optional active Downloader instance for live concurrency updates.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.repo = repository or SettingsRepository(db_manager=DatabaseManager())
        self.downloader = downloader

        self._init_ui()
        self.load_settings()

    def _init_ui(self) -> None:
        """Construct the settings page layout with smooth scrolling and responsive components."""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Scroll area for all configuration sections
        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll_area.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")

        # Scroll content widget
        content_widget = QWidget()
        content_widget.setObjectName("settingsScrollContent")
        content_widget.setStyleSheet("background-color: transparent;")

        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(32, 24, 32, 28)
        content_layout.setSpacing(22)

        # Header Title & Description
        header_box = QVBoxLayout()
        header_box.setSpacing(6)
        title_label = QLabel("Settings", content_widget)
        title_label.setObjectName("pageTitle")
        header_box.addWidget(title_label)

        desc_label = QLabel(
            "Configure download storage, network concurrency limits, and media processing engine.",
            content_widget,
        )
        desc_label.setObjectName("secondaryText")
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"color: {COLORS.text_secondary}; font-size: 13px; line-height: 1.4;")
        header_box.addWidget(desc_label)
        content_layout.addLayout(header_box)

        content_layout.addWidget(self._create_divider(content_widget))

        # Section 1: Storage & Download Directory
        sec1_header = QLabel("Storage & Download Directory", content_widget)
        sec1_header.setObjectName("sectionHeader")
        sec1_header.setStyleSheet(
            f"font-size: 12px; font-weight: 700; text-transform: uppercase; "
            f"color: {COLORS.text_secondary}; letter-spacing: 0.5px;"
        )
        content_layout.addWidget(sec1_header)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(10)

        self._dir_input = QLineEdit(content_widget)
        self._dir_input.setPlaceholderText("Select download directory...")
        self._dir_input.setMinimumHeight(38)
        self._dir_input.textChanged.connect(self._clear_inline_errors)
        dir_row.addWidget(self._dir_input, 1)

        browse_dir_btn = QPushButton("Browse...", content_widget)
        browse_dir_btn.setIcon(create_vector_icon("folder", size=14))
        browse_dir_btn.setMinimumHeight(38)
        browse_dir_btn.clicked.connect(self._on_browse_directory)
        dir_row.addWidget(browse_dir_btn)

        open_dir_btn = QPushButton("Open Folder", content_widget)
        open_dir_btn.setMinimumHeight(38)
        open_dir_btn.clicked.connect(self._on_open_directory)
        dir_row.addWidget(open_dir_btn)

        content_layout.addLayout(dir_row)

        self._dir_error_label = QLabel(content_widget)
        self._dir_error_label.setStyleSheet(f"color: {COLORS.status_danger}; font-size: 12px; font-weight: 500;")
        self._dir_error_label.setWordWrap(True)
        self._dir_error_label.hide()
        content_layout.addWidget(self._dir_error_label)

        dir_hint = QLabel(
            "All downloaded video, audio, and drama series files will be saved into this folder.",
            content_widget,
        )
        dir_hint.setWordWrap(True)
        dir_hint.setStyleSheet(f"color: {COLORS.text_secondary}; font-size: 12px; line-height: 1.4;")
        content_layout.addWidget(dir_hint)

        content_layout.addWidget(self._create_divider(content_widget))

        # Section 2: Concurrency & Performance
        sec2_header = QLabel("Concurrency & Performance", content_widget)
        sec2_header.setObjectName("sectionHeader")
        sec2_header.setStyleSheet(
            f"font-size: 12px; font-weight: 700; text-transform: uppercase; "
            f"color: {COLORS.text_secondary}; letter-spacing: 0.5px;"
        )
        content_layout.addWidget(sec2_header)

        concurrency_row = QHBoxLayout()
        concurrency_row.setSpacing(16)

        concurrency_label = QLabel("Simultaneous Downloads:", content_widget)
        concurrency_label.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {COLORS.text_primary};")
        concurrency_row.addWidget(concurrency_label)

        self._concurrency_slider = QSlider(Qt.Orientation.Horizontal, content_widget)
        self._concurrency_slider.setRange(1, 20)
        self._concurrency_slider.setValue(3)
        self._concurrency_slider.setFixedWidth(240)
        self._concurrency_slider.setMinimumHeight(32)
        concurrency_row.addWidget(self._concurrency_slider)

        self._concurrency_spinbox = QSpinBox(content_widget)
        self._concurrency_spinbox.setRange(1, 20)
        self._concurrency_spinbox.setValue(3)
        self._concurrency_spinbox.setFixedWidth(75)
        self._concurrency_spinbox.setMinimumHeight(38)
        concurrency_row.addWidget(self._concurrency_spinbox)

        # Synchronize slider and spinbox
        self._concurrency_slider.valueChanged.connect(self._concurrency_spinbox.setValue)
        self._concurrency_spinbox.valueChanged.connect(self._concurrency_slider.setValue)

        concurrency_row.addStretch()
        content_layout.addLayout(concurrency_row)

        concurrency_hint = QLabel(
            "Controls the maximum number of simultaneous background downloads (1 to 20).",
            content_widget,
        )
        concurrency_hint.setWordWrap(True)
        concurrency_hint.setStyleSheet(f"color: {COLORS.text_secondary}; font-size: 12px; line-height: 1.4;")
        content_layout.addWidget(concurrency_hint)

        content_layout.addWidget(self._create_divider(content_widget))

        # Section 3: Media Processing Engine (FFmpeg)
        sec3_header = QLabel("FFmpeg Media Engine", content_widget)
        sec3_header.setObjectName("sectionHeader")
        sec3_header.setStyleSheet(
            f"font-size: 12px; font-weight: 700; text-transform: uppercase; "
            f"color: {COLORS.text_secondary}; letter-spacing: 0.5px;"
        )
        content_layout.addWidget(sec3_header)

        ffmpeg_status_row = QHBoxLayout()
        ffmpeg_status_row.setSpacing(10)
        ffmpeg_lbl = QLabel("Engine Status:", content_widget)
        ffmpeg_lbl.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {COLORS.text_primary};")
        ffmpeg_status_row.addWidget(ffmpeg_lbl)

        self._ffmpeg_status_badge = QLabel("Checking...", content_widget)
        self._ffmpeg_status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ffmpeg_status_badge.setMinimumHeight(26)
        self._ffmpeg_status_badge.setStyleSheet(
            f"padding: 4px 12px; border-radius: 4px; font-size: 11px; font-weight: 600; "
            f"color: {COLORS.text_muted}; background-color: {COLORS.bg_surface_alt};"
        )
        ffmpeg_status_row.addWidget(self._ffmpeg_status_badge)

        self._ffmpeg_desc_label = QLabel(content_widget)
        self._ffmpeg_desc_label.setWordWrap(True)
        self._ffmpeg_desc_label.setStyleSheet(f"color: {COLORS.text_secondary}; font-size: 12px;")
        ffmpeg_status_row.addWidget(self._ffmpeg_desc_label, 1)

        content_layout.addLayout(ffmpeg_status_row)

        ffmpeg_row = QHBoxLayout()
        ffmpeg_row.setSpacing(10)

        self._ffmpeg_input = QLineEdit(content_widget)
        self._ffmpeg_input.setPlaceholderText("Custom FFmpeg binary path (optional, e.g. /usr/local/bin/ffmpeg)")
        self._ffmpeg_input.setMinimumHeight(38)
        self._ffmpeg_input.textChanged.connect(self._on_ffmpeg_text_changed)
        ffmpeg_row.addWidget(self._ffmpeg_input, 1)

        browse_ffmpeg_btn = QPushButton("Browse...", content_widget)
        browse_ffmpeg_btn.setMinimumHeight(38)
        browse_ffmpeg_btn.clicked.connect(self._on_browse_ffmpeg)
        ffmpeg_row.addWidget(browse_ffmpeg_btn)

        test_ffmpeg_btn = QPushButton("Test Binary", content_widget)
        test_ffmpeg_btn.setMinimumHeight(38)
        test_ffmpeg_btn.clicked.connect(self._on_test_ffmpeg)
        ffmpeg_row.addWidget(test_ffmpeg_btn)

        content_layout.addLayout(ffmpeg_row)

        ffmpeg_hint = QLabel(
            "FFmpeg is used to mux high-definition video (1080p, 4K) with separate audio streams.",
            content_widget,
        )
        ffmpeg_hint.setWordWrap(True)
        ffmpeg_hint.setStyleSheet(f"color: {COLORS.text_secondary}; font-size: 12px; line-height: 1.4;")
        content_layout.addWidget(ffmpeg_hint)

        content_layout.addWidget(self._create_divider(content_widget))

        # Section 4: Authentication & Cookies (cookies.txt)
        sec4_header = QLabel("Authentication & Cookies", content_widget)
        sec4_header.setObjectName("sectionHeader")
        sec4_header.setStyleSheet(
            f"font-size: 12px; font-weight: 700; text-transform: uppercase; "
            f"color: {COLORS.text_secondary}; letter-spacing: 0.5px;"
        )
        content_layout.addWidget(sec4_header)

        cookies_status_row = QHBoxLayout()
        cookies_status_row.setSpacing(10)
        cookies_lbl = QLabel("Cookies Status:", content_widget)
        cookies_lbl.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {COLORS.text_primary};")
        cookies_status_row.addWidget(cookies_lbl)

        self._cookies_status_badge = QLabel("Not Configured", content_widget)
        self._cookies_status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cookies_status_badge.setMinimumHeight(26)
        self._cookies_status_badge.setStyleSheet(
            f"padding: 4px 12px; border-radius: 4px; font-size: 11px; font-weight: 600; "
            f"color: {COLORS.text_muted}; background-color: {COLORS.bg_surface_alt};"
        )
        cookies_status_row.addWidget(self._cookies_status_badge)

        self._cookies_desc_label = QLabel(content_widget)
        self._cookies_desc_label.setWordWrap(True)
        self._cookies_desc_label.setStyleSheet(f"color: {COLORS.text_secondary}; font-size: 12px;")
        cookies_status_row.addWidget(self._cookies_desc_label, 1)

        content_layout.addLayout(cookies_status_row)

        # Auto-detect from installed browser
        browser_row = QHBoxLayout()
        browser_row.setSpacing(12)
        browser_lbl = QLabel("Auto-detect Browser:", content_widget)
        browser_lbl.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {COLORS.text_primary};")
        browser_row.addWidget(browser_lbl)

        self._browser_combo = QComboBox(content_widget)
        self._browser_combo.setMinimumHeight(38)
        self._browser_combo.addItem("Disabled (Use manual cookies.txt / Off)", "")
        self._browser_combo.addItem("Google Chrome", "chrome")
        self._browser_combo.addItem("Microsoft Edge", "edge")
        self._browser_combo.addItem("Mozilla Firefox", "firefox")
        self._browser_combo.addItem("Brave Browser", "brave")
        self._browser_combo.addItem("Apple Safari", "safari")
        self._browser_combo.currentIndexChanged.connect(self._on_browser_changed)
        browser_row.addWidget(self._browser_combo)
        browser_row.addStretch()
        content_layout.addLayout(browser_row)

        manual_cookie_lbl = QLabel("Or specify cookies.txt file manually:", content_widget)
        manual_cookie_lbl.setWordWrap(True)
        manual_cookie_lbl.setStyleSheet(f"color: {COLORS.text_secondary}; font-size: 12px;")
        content_layout.addWidget(manual_cookie_lbl)

        cookies_row = QHBoxLayout()
        cookies_row.setSpacing(10)

        self._cookies_input = QLineEdit(content_widget)
        self._cookies_input.setPlaceholderText("Path to exported cookies.txt (e.g. ~/Downloads/cookies.txt)")
        self._cookies_input.setMinimumHeight(38)
        self._cookies_input.textChanged.connect(self._on_cookies_text_changed)
        cookies_row.addWidget(self._cookies_input, 1)

        browse_cookies_btn = QPushButton("Browse...", content_widget)
        browse_cookies_btn.setIcon(create_vector_icon("folder", size=14))
        browse_cookies_btn.setMinimumHeight(38)
        browse_cookies_btn.clicked.connect(self._on_browse_cookies)
        cookies_row.addWidget(browse_cookies_btn)

        clear_cookies_btn = QPushButton("Clear", content_widget)
        clear_cookies_btn.setMinimumHeight(38)
        clear_cookies_btn.clicked.connect(self._on_clear_cookies)
        cookies_row.addWidget(clear_cookies_btn)

        content_layout.addLayout(cookies_row)

        self._cookies_error_label = QLabel(content_widget)
        self._cookies_error_label.setStyleSheet(f"color: {COLORS.status_danger}; font-size: 12px; font-weight: 500;")
        self._cookies_error_label.setWordWrap(True)
        self._cookies_error_label.hide()
        content_layout.addWidget(self._cookies_error_label)

        cookies_hint = QLabel(
            "Auto-detect reads cookies directly from your browser, or specify an exported Netscape cookies.txt to download login-gated TikTok dramas and private videos.",
            content_widget,
        )
        cookies_hint.setWordWrap(True)
        cookies_hint.setStyleSheet(f"color: {COLORS.text_secondary}; font-size: 12px; line-height: 1.4;")
        content_layout.addWidget(cookies_hint)

        content_layout.addStretch(1)

        self._scroll_area.setWidget(content_widget)
        root_layout.addWidget(self._scroll_area, 1)

        # Pinned Footer Actions Container
        footer_container = QWidget(self)
        footer_container.setObjectName("settingsFooterContainer")
        footer_container.setStyleSheet(
            f"QWidget#settingsFooterContainer {{"
            f"  background-color: {COLORS.bg_surface};"
            f"  border-top: 1px solid {COLORS.border_subtle};"
            f"}}"
        )
        footer_layout = QHBoxLayout(footer_container)
        footer_layout.setContentsMargins(32, 14, 32, 16)
        footer_layout.setSpacing(12)

        save_btn = QPushButton("Save Settings", footer_container)
        save_btn.setObjectName("primaryButton")
        save_btn.setMinimumHeight(38)
        save_btn.setMinimumWidth(130)
        save_btn.clicked.connect(self.save_settings)
        footer_layout.addWidget(save_btn)

        defaults_btn = QPushButton("Restore Defaults", footer_container)
        defaults_btn.setMinimumHeight(38)
        defaults_btn.setMinimumWidth(130)
        defaults_btn.clicked.connect(self.restore_defaults)
        footer_layout.addWidget(defaults_btn)

        self._footer_status_label = QLabel(footer_container)
        self._footer_status_label.setStyleSheet(
            f"color: {COLORS.status_success}; font-size: 12px; font-weight: 500;"
        )
        self._footer_status_label.setWordWrap(True)
        self._footer_status_label.hide()
        footer_layout.addWidget(self._footer_status_label, 1)

        footer_layout.addStretch()
        root_layout.addWidget(footer_container, 0)

    def _create_divider(self, parent: Optional[QWidget] = None) -> QFrame:
        """Create a flat 1px subtle divider line."""
        line = QFrame(parent or self)
        line.setObjectName("dividerLine")
        line.setFrameShape(QFrame.Shape.HLine)
        return line

    def load_settings(self) -> None:
        """Load stored settings from SQLite repository or defaults from config."""
        config = get_config()

        # Download directory
        saved_dir = self.repo.get(KEY_DOWNLOAD_DIR, str(config.download_dir))
        self._dir_input.setText(saved_dir or str(config.download_dir))

        # Concurrency
        saved_concurrency = self.repo.get(KEY_MAX_CONCURRENT, str(config.max_concurrent_downloads))
        concurrency = clamp_concurrency(saved_concurrency)
        self._concurrency_slider.setValue(concurrency)
        self._concurrency_spinbox.setValue(concurrency)

        # FFmpeg path
        saved_ffmpeg = self.repo.get(KEY_FFMPEG_PATH, config.ffmpeg_path)
        self._ffmpeg_input.setText(saved_ffmpeg or "")

        # Browser auto-detection
        saved_browser = self.repo.get(KEY_COOKIES_BROWSER, "")
        idx = self._browser_combo.findData(saved_browser)
        if idx >= 0:
            self._browser_combo.setCurrentIndex(idx)

        # Cookies file
        saved_cookies = self.repo.get(KEY_COOKIES_FILE, "")
        self._cookies_input.setText(saved_cookies or "")

        self._update_ffmpeg_indicator(saved_ffmpeg)
        self._update_cookies_indicator(saved_cookies, saved_browser)

    def save_settings(self) -> bool:
        """Validate and persist current settings to SQLite repository.

        Returns:
            True if settings were saved successfully, False if validation failed.
        """
        dir_candidate = self._dir_input.text().strip()
        is_valid_dir, dir_result = validate_download_directory(dir_candidate)
        if not is_valid_dir:
            self._dir_error_label.setText(dir_result)
            self._dir_error_label.show()
            self._show_footer_status("Please fix configuration errors above.", is_error=True)
            return False

        self._dir_error_label.hide()

        cookies_candidate = self._cookies_input.text().strip()
        is_valid_cookies, cookies_result = validate_cookies_file(cookies_candidate)
        if not is_valid_cookies:
            self._cookies_error_label.setText(cookies_result)
            self._cookies_error_label.show()
            self._show_footer_status("Please fix configuration errors above.", is_error=True)
            return False

        self._cookies_error_label.hide()

        concurrency = clamp_concurrency(self._concurrency_spinbox.value())
        ffmpeg_val = self._ffmpeg_input.text().strip()
        browser_val = self._browser_combo.currentData() or ""

        # Persist to database
        self.repo.set(KEY_DOWNLOAD_DIR, dir_result)
        self.repo.set(KEY_MAX_CONCURRENT, str(concurrency))
        self.repo.set(KEY_FFMPEG_PATH, ffmpeg_val)
        self.repo.set(KEY_COOKIES_FILE, cookies_result)
        self.repo.set(KEY_COOKIES_BROWSER, browser_val)

        # If a browser is selected and no manual cookie file is set, export cookies in background
        if browser_val and not cookies_result:
            import threading
            from app.services.cookie_service import CookieService

            threading.Thread(
                target=CookieService.export_browser_cookies,
                args=(browser_val,),
                daemon=True,
            ).start()

        # Apply live concurrency and storage directory to Downloader instance if available
        if self.downloader:
            self.downloader.set_max_concurrent(concurrency)
            self.downloader.storage.base_download_dir = Path(dir_result).resolve()
            logger.info("Updated live Downloader worker pool concurrency to %d and storage to %s", concurrency, dir_result)

        payload = {
            KEY_DOWNLOAD_DIR: dir_result,
            KEY_MAX_CONCURRENT: concurrency,
            KEY_FFMPEG_PATH: ffmpeg_val,
            KEY_COOKIES_FILE: cookies_result,
            KEY_COOKIES_BROWSER: browser_val,
        }
        self.settings_saved.emit(payload)

        self._show_footer_status("Settings saved successfully.", is_error=False)
        self._update_ffmpeg_indicator(ffmpeg_val)
        self._update_cookies_indicator(cookies_result, browser_val)
        return True

    def restore_defaults(self) -> None:
        """Reset inputs back to system configuration defaults."""
        config = get_config()
        self._dir_input.setText(str(config.download_dir))
        self._concurrency_slider.setValue(clamp_concurrency(config.max_concurrent_downloads))
        self._concurrency_spinbox.setValue(clamp_concurrency(config.max_concurrent_downloads))
        self._ffmpeg_input.setText(config.ffmpeg_path)
        self._browser_combo.setCurrentIndex(0)
        self._cookies_input.setText("")
        self._clear_inline_errors()
        self._update_ffmpeg_indicator(config.ffmpeg_path)
        self._update_cookies_indicator("", "")
        self._show_footer_status("Defaults restored. Click 'Save Settings' to apply.", is_error=False)

    def _on_browse_directory(self) -> None:
        """Open system folder picker to select download directory."""
        current_dir = self._dir_input.text().strip() or str(Path.home())
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Download Directory",
            current_dir,
            QFileDialog.Option.ShowDirsOnly,
        )
        if selected:
            self._dir_input.setText(str(Path(selected).resolve()))
            self._clear_inline_errors()

    def _on_open_directory(self) -> None:
        """Open current download directory in Windows File Explorer."""
        current_dir = self._dir_input.text().strip()
        is_valid, resolved = validate_download_directory(current_dir)
        if is_valid:
            QDesktopServices.openUrl(QUrl.fromLocalFile(resolved))
        else:
            self._dir_error_label.setText(resolved)
            self._dir_error_label.show()

    def _on_browse_ffmpeg(self) -> None:
        """Open system file picker to select custom ffmpeg executable."""
        current_val = self._ffmpeg_input.text().strip() or str(Path.home())
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select FFmpeg Executable",
            current_val,
            "Executable Files (*.exe);;All Files (*)",
        )
        if selected:
            self._ffmpeg_input.setText(str(Path(selected).resolve()))
            self._on_test_ffmpeg()

    def _on_test_ffmpeg(self) -> None:
        """Test and update FFmpeg binary status."""
        candidate = self._ffmpeg_input.text().strip()
        self._update_ffmpeg_indicator(candidate)

    def _on_ffmpeg_text_changed(self) -> None:
        """Update FFmpeg indicator as user edits custom path."""
        candidate = self._ffmpeg_input.text().strip()
        self._update_ffmpeg_indicator(candidate)

    def _update_ffmpeg_indicator(self, custom_path: Optional[str]) -> None:
        """Update visual badge and description for FFmpeg status."""
        is_avail, desc = resolve_ffmpeg_status(custom_path)
        if is_avail:
            self._ffmpeg_status_badge.setText("Active")
            self._ffmpeg_status_badge.setStyleSheet(
                f"padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; "
                f"color: #ffffff; background-color: {COLORS.status_success};"
            )
        else:
            self._ffmpeg_status_badge.setText("Not Found")
            self._ffmpeg_status_badge.setStyleSheet(
                f"padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; "
                f"color: #ffffff; background-color: {COLORS.status_warning};"
            )
        self._ffmpeg_desc_label.setText(desc)

    def _on_browse_cookies(self) -> None:
        """Open system file picker to select cookies.txt file."""
        current_val = self._cookies_input.text().strip() or str(Path.home())
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select Netscape cookies.txt File",
            current_val,
            "Text Files (*.txt);;All Files (*)",
        )
        if selected:
            self._cookies_input.setText(str(Path(selected).resolve()))
            self._clear_inline_errors()
            self._update_cookies_indicator(self._cookies_input.text())

    def _on_clear_cookies(self) -> None:
        """Clear the cookies file input."""
        self._cookies_input.setText("")
        self._clear_inline_errors()
        self._update_cookies_indicator("")

    def _on_browser_changed(self) -> None:
        """Update cookies indicator when user selects a browser."""
        browser_val = self._browser_combo.currentData() or ""
        cookies_val = self._cookies_input.text().strip()
        self._update_cookies_indicator(cookies_val, browser_val)

    def _on_cookies_text_changed(self) -> None:
        """Update cookies indicator as user types or edits path."""
        browser_val = self._browser_combo.currentData() or ""
        candidate = self._cookies_input.text().strip()
        self._update_cookies_indicator(candidate, browser_val)

    def _update_cookies_indicator(
        self,
        custom_path: Optional[str] = None,
        browser: Optional[str] = None,
    ) -> None:
        """Update visual badge and description for cookies status."""
        active_browser = browser if browser is not None else (self._browser_combo.currentData() or "")
        active_path = custom_path if custom_path is not None else self._cookies_input.text().strip()

        if active_browser:
            browser_name = self._browser_combo.currentText()
            self._cookies_status_badge.setText("Active (Browser)")
            self._cookies_status_badge.setStyleSheet(
                f"padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; "
                f"color: #ffffff; background-color: {COLORS.status_success};"
            )
            self._cookies_desc_label.setText(f"Auto-detecting cookies from {browser_name}")
            return

        if not active_path:
            self._cookies_status_badge.setText("Not Configured")
            self._cookies_status_badge.setStyleSheet(
                f"padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; "
                f"color: {COLORS.text_muted}; background-color: {COLORS.bg_surface_alt};"
            )
            self._cookies_desc_label.setText("Optional. Configure to download login-gated videos.")
            return

        is_valid, resolved = validate_cookies_file(active_path)
        if is_valid:
            self._cookies_status_badge.setText("Active (File)")
            self._cookies_status_badge.setStyleSheet(
                f"padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; "
                f"color: #ffffff; background-color: {COLORS.status_success};"
            )
            self._cookies_desc_label.setText(f"Loaded: {resolved}")
        else:
            self._cookies_status_badge.setText("Invalid File")
            self._cookies_status_badge.setStyleSheet(
                f"padding: 3px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; "
                f"color: #ffffff; background-color: {COLORS.status_warning};"
            )
            self._cookies_desc_label.setText(resolved)

    def _clear_inline_errors(self) -> None:
        """Clear visible inline validation errors."""
        self._dir_error_label.hide()
        self._dir_error_label.setText("")
        self._cookies_error_label.hide()
        self._cookies_error_label.setText("")

    def _show_footer_status(self, text: str, is_error: bool = False) -> None:
        """Display an inline status message in the footer."""
        color = COLORS.status_danger if is_error else COLORS.status_success
        self._footer_status_label.setStyleSheet(f"color: {color}; font-size: 12px; font-weight: 500;")
        self._footer_status_label.setText(text)
        self._footer_status_label.show()
