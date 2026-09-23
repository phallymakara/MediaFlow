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

    env: str = "development"
    log_level: str = "INFO"
    download_dir: Path = Path("downloads")
    temp_dir: Path = Path("downloads/.temp")
    max_concurrent_downloads: int = 3
    max_download_bytes: int = 10 * 1024 * 1024 * 1024
    db_path: Path = Path("mediaflow.db")
    ffmpeg_path: str = ""
    ffprobe_path: str = ""
    license_secret: str = "mediaflow_secret_key_v1_offline_auth"

    def __post_init__(self) -> None:
        """Validate production configuration boundaries."""
        if self.env.lower() == "production":
            raw_secret = self.license_secret.strip()
            if not raw_secret or len(raw_secret) < 16 or raw_secret == "mediaflow_secret_key_v1_offline_auth":
                raise ValueError("CRITICAL: MEDIAFLOW_LICENSE_SECRET must be explicitly set and at least 16 characters long in production.")

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Load configuration dynamically from environment variables."""
        return cls(
            env=os.getenv("APP_ENV", "development"),
            log_level=os.getenv("APP_LOG_LEVEL", "INFO"),
            download_dir=Path(os.getenv("MEDIAFLOW_DOWNLOAD_DIR", "downloads")),
            temp_dir=Path(os.getenv("MEDIAFLOW_TEMP_DIR", "downloads/.temp")),
            max_concurrent_downloads=max(1, min(int(os.getenv("MEDIAFLOW_MAX_CONCURRENT_DOWNLOADS", "3")), 20)),
            max_download_bytes=int(os.getenv("MEDIAFLOW_MAX_DOWNLOAD_BYTES", str(10 * 1024 * 1024 * 1024))),
            db_path=Path(os.getenv("MEDIAFLOW_DB_PATH", "mediaflow.db")),
            ffmpeg_path=os.getenv("FFMPEG_PATH", ""),
            ffprobe_path=os.getenv("FFPROBE_PATH", ""),
            license_secret=os.getenv("MEDIAFLOW_LICENSE_SECRET", "mediaflow_secret_key_v1_offline_auth"),
        )


def get_config() -> AppConfig:
    """Return the active application configuration instance."""
    return AppConfig.from_env()
