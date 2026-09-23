"""Application entry point and desktop launcher for MediaFlow."""

import argparse
import logging
import os
from pathlib import Path
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure Qt can locate platform plugins on Windows inside virtual environments
try:
    import PySide6

    _pyside_dir = Path(PySide6.__file__).parent
    _platforms_dir = _pyside_dir / "plugins" / "platforms"
    if _platforms_dir.is_dir() and "QT_QPA_PLATFORM_PLUGIN_PATH" not in os.environ:
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(_platforms_dir)
    _plugins_dir = _pyside_dir / "plugins"
    if _plugins_dir.is_dir() and "QT_PLUGIN_PATH" not in os.environ:
        os.environ["QT_PLUGIN_PATH"] = str(_plugins_dir)
except Exception:
    pass

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.config import get_config
from app.core.downloader import Downloader
from app.core.extractor_registry import ExtractorRegistry
from app.database.database import DatabaseManager
from app.database.repository import DownloadRepository, SettingsRepository
from app.gui.assets import get_logo_pixmap
from app.gui.main_window import MainWindow
from app.gui.styles import get_application_stylesheet
from app.services.ffmpeg import FFmpegService
from app.services.license import LicenseService
from app.services.storage import StorageService

logger = logging.getLogger("mediaflow")


def setup_logging(log_level_name: str = "INFO") -> None:
    """Configure structured console logging for the application.

    Args:
        log_level_name: Log level string (e.g. INFO, DEBUG).
    """
    level = getattr(logging, log_level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Reduce noise from chatty external libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def verify_application() -> int:
    """Perform headless self-check of database, services, and core models.

    Returns:
        0 on success, non-zero on failure.
    """
    try:
        config = get_config()
        logger.info("Verifying MediaFlow components in headless verification mode...")

        # 1. Database check
        db_manager = DatabaseManager(db_path=config.db_path)
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [row["name"] for row in cursor.fetchall()]
            logger.info("Verified database schema tables: %s", tables)
            assert "downloads" in tables, "Missing 'downloads' table"
            assert "settings" in tables, "Missing 'settings' table"

        # 2. Services check
        settings_repo = SettingsRepository(db_manager=db_manager)
        download_repo = DownloadRepository(db_manager=db_manager)
        storage_service = StorageService()
        ffmpeg_service = FFmpegService()
        license_service = LicenseService(settings_repo=settings_repo)
        extractor_registry = ExtractorRegistry()

        downloader = Downloader(
            storage_service=storage_service,
            ffmpeg_service=ffmpeg_service,
            repository=download_repo,
        )

        # 3. License state check
        license_info = license_service.get_current_license()
        logger.info("Current license state: status=%s, valid=%s", license_info.status.value, license_info.is_valid)

        # Shutdown downloader pool
        downloader.shutdown(wait=False)

        logger.info("MediaFlow desktop application verified successfully.")
        return 0
    except Exception as exc:
        logger.critical("MediaFlow verification failed: %s", exc, exc_info=True)
        return 1


def main() -> None:
    """Launch the MediaFlow desktop application."""
    parser = argparse.ArgumentParser(description="MediaFlow Desktop Media Downloader")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Perform headless initialization and schema verification without opening GUI window.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Log level (DEBUG, INFO, WARNING, ERROR).",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)

    if args.verify:
        sys.exit(verify_application())

    # Initialize Qt GUI application
    app = QApplication(sys.argv)
    if "QT_PLUGIN_PATH" in os.environ:
        QCoreApplication.addLibraryPath(os.environ["QT_PLUGIN_PATH"])

    app.setApplicationName("MediaFlow")
    app.setOrganizationName("Proseth")
    app.setWindowIcon(QIcon(get_logo_pixmap(size=32)))

    # Apply global QSS dark theme stylesheet
    app.setStyleSheet(get_application_stylesheet())

    # Construct shared singletons
    config = get_config()
    db_manager = DatabaseManager(db_path=config.db_path)
    download_repo = DownloadRepository(db_manager=db_manager)
    settings_repo = SettingsRepository(db_manager=db_manager)
    storage_service = StorageService()
    ffmpeg_service = FFmpegService()
    license_service = LicenseService(settings_repo=settings_repo)
    extractor_registry = ExtractorRegistry()

    downloader = Downloader(
        storage_service=storage_service,
        ffmpeg_service=ffmpeg_service,
        repository=download_repo,
    )

    window = MainWindow(
        downloader=downloader,
        download_repo=download_repo,
        settings_repo=settings_repo,
        license_service=license_service,
        extractor_registry=extractor_registry,
        storage_service=storage_service,
        ffmpeg_service=ffmpeg_service,
    )
    window.show()

    logger.info("MediaFlow GUI initialized and running.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
