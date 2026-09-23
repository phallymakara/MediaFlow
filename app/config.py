"""Application configuration module."""

from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()


@dataclass(frozen=True)
class AppConfig:
    """Immutable application configuration loaded from environment variables."""

    env: str = os.getenv("APP_ENV", "development")
    log_level: str = os.getenv("APP_LOG_LEVEL", "INFO")
    download_dir: Path = Path(os.getenv("MEDIAFLOW_DOWNLOAD_DIR", "downloads"))
    temp_dir: Path = Path(os.getenv("MEDIAFLOW_TEMP_DIR", "downloads/.temp"))
    max_concurrent_downloads: int = int(os.getenv("MEDIAFLOW_MAX_CONCURRENT_DOWNLOADS", "3"))
    db_path: Path = Path(os.getenv("MEDIAFLOW_DB_PATH", "mediaflow.db"))
    ffmpeg_path: str = os.getenv("FFMPEG_PATH", "")
    ffprobe_path: str = os.getenv("FFPROBE_PATH", "")
    license_secret: str = os.getenv("MEDIAFLOW_LICENSE_SECRET", "mediaflow_secret_key_v1_offline_auth")


def get_config() -> AppConfig:
    """Return the active application configuration instance."""
    return AppConfig()
