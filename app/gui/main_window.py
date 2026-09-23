"""Main application window uniting navigation sidebar and application pages."""

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QWidget,
)

from app.core.downloader import Downloader
from app.core.extractor_registry import ExtractorRegistry
from app.database.database import DatabaseManager
from app.database.repository import DownloadRepository, SettingsRepository
from app.gui.assets import get_logo_pixmap
from app.gui.downloader_page import DownloaderPage
from app.gui.history_page import HistoryPage
from app.gui.license_page import LicensePage
from app.gui.settings_page import KEY_DOWNLOAD_DIR, SettingsPage
from app.gui.widgets.sidebar import Sidebar
from app.services.ffmpeg import FFmpegService
from app.services.license import LicenseService
from app.services.storage import StorageService

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Primary application window hosting the global navigation and page stack."""

    def __init__(
        self,
        downloader: Optional[Downloader] = None,
        download_repo: Optional[DownloadRepository] = None,
        settings_repo: Optional[SettingsRepository] = None,
        license_service: Optional[LicenseService] = None,
        extractor_registry: Optional[ExtractorRegistry] = None,
        storage_service: Optional[StorageService] = None,
        ffmpeg_service: Optional[FFmpegService] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """Initialize main window and dependencies.

        Args:
            downloader: Optional Downloader service.
            download_repo: Optional DownloadRepository instance.
            settings_repo: Optional SettingsRepository instance.
            license_service: Optional LicenseService instance.
            extractor_registry: Optional ExtractorRegistry instance.
            storage_service: Optional StorageService instance.
            ffmpeg_service: Optional FFmpegService instance.
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setObjectName("mainWindow")
        self.setWindowTitle("MediaFlow")
        self.setWindowIcon(QIcon(get_logo_pixmap(size=32)))
        self.setMinimumSize(1050, 700)
        self.resize(1150, 760)

        # Initialize or reuse shared singletons
        db_manager = DatabaseManager()
        self.download_repo = download_repo or DownloadRepository(db_manager=db_manager)
        self.settings_repo = settings_repo or SettingsRepository(db_manager=db_manager)
        self.license_service = license_service or LicenseService(settings_repo=self.settings_repo)
        self.storage_service = storage_service or StorageService()
        self.ffmpeg_service = ffmpeg_service or FFmpegService()
        self.extractor_registry = extractor_registry or ExtractorRegistry()

        self.downloader = downloader or Downloader(
            storage_service=self.storage_service,
            ffmpeg_service=self.ffmpeg_service,
            repository=self.download_repo,
        )

        self._init_ui()
        self._wire_signals()

    def _init_ui(self) -> None:
        """Set up central layout with Sidebar and QStackedWidget."""
        central_widget = QWidget(self)
        central_widget.setObjectName("centralContainer")
        self.setCentralWidget(central_widget)

        root_layout = QHBoxLayout(central_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Navigation Sidebar
        self._sidebar = Sidebar(self)
        root_layout.addWidget(self._sidebar)

        # 2. Page Stack
        self._stack = QStackedWidget(self)
        self._stack.setObjectName("contentFrame")

        # Page 0: Downloader
        self._downloader_page = DownloaderPage(
            downloader=self.downloader,
            extractor_registry=self.extractor_registry,
            license_service=self.license_service,
            parent=self,
        )
        self._stack.addWidget(self._downloader_page)

        # Page 1: History
        self._history_page = HistoryPage(
            repository=self.download_repo,
            parent=self,
        )
        self._stack.addWidget(self._history_page)

        # Page 2: Settings
        self._settings_page = SettingsPage(
            repository=self.settings_repo,
            downloader=self.downloader,
            parent=self,
        )
        self._stack.addWidget(self._settings_page)

        # Page 3: License
        self._license_page = LicensePage(
            license_service=self.license_service,
            parent=self,
        )
        self._stack.addWidget(self._license_page)

        root_layout.addWidget(self._stack, 1)

        # Sync initial license state to sidebar
        init_license = self.license_service.get_current_license()
        self._sidebar.update_license_display(init_license)

    def _wire_signals(self) -> None:
        """Connect cross-page and navigation signals."""
        # Navigation
        self._sidebar.page_changed.connect(self._on_page_changed)

        # License updates reflect immediately on sidebar
        self._license_page.license_updated.connect(self._sidebar.update_license_display)

        # Settings save updates storage directory and config
        self._settings_page.settings_saved.connect(self._on_settings_saved)

    def _on_page_changed(self, index: int) -> None:
        """Handle page switching and perform page-specific refresh.

        Args:
            index: New active stacked page index.
        """
        self._stack.setCurrentIndex(index)
        if index == 1:
            self._history_page.reload_history()
        elif index == 3:
            self._license_page.refresh_status()

    def _on_settings_saved(self, payload: dict) -> None:
        """Handle settings saved event and update runtime services.

        Args:
            payload: Dictionary of updated setting keys and values.
        """
        if KEY_DOWNLOAD_DIR in payload:
            new_dir = Path(payload[KEY_DOWNLOAD_DIR]).resolve()
            self.storage_service.base_download_dir = new_dir
            logger.info("Updated base download directory to %s", new_dir)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Ensure background download workers are cleanly halted before exiting.

        Args:
            event: Window close event.
        """
        logger.info("MainWindow closing, initiating graceful downloader shutdown...")
        if self.downloader:
            try:
                self.downloader.shutdown(wait=False)
            except Exception as exc:
                logger.error("Error during downloader shutdown: %s", exc)
        event.accept()
