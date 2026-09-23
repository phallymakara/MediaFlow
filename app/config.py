"""Application configuration module."""

from dataclasses import dataclass
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()


DEFAULT_DEV_PUBLIC_KEY = "6U/skrlCsriF4GXxv0an0l4onAA8tqBnweVT16D5Ym4="
DEFAULT_DEV_PRIVATE_KEY = "vKEyXE/y+KKGO4mtw9uyv0yG2RBCm0fZUQCfM36lOeU="


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
    license_public_key: str = DEFAULT_DEV_PUBLIC_KEY
    license_private_key: str = DEFAULT_DEV_PRIVATE_KEY
    license_secret: str = "mediaflow_secret_key_v1_offline_auth"

    def __post_init__(self) -> None:
        """Validate production configuration boundaries."""
        if self.env.lower() == "production":
            raw_secret = self.license_secret.strip()
            if not raw_secret or len(raw_secret) < 16 or raw_secret == "mediaflow_secret_key_v1_offline_auth":
                raise ValueError(
                    "CRITICAL: MEDIAFLOW_LICENSE_SECRET must be explicitly set and at least 16 characters long in production."
                )


    @classmethod
    def from_env(cls) -> "AppConfig":
        """Load configuration dynamically from environment variables."""
        env_val = os.getenv("APP_ENV", "development").strip()
        pub_key = os.getenv("MEDIAFLOW_LICENSE_PUBLIC_KEY", "").strip()
        priv_key = os.getenv("MEDIAFLOW_LICENSE_PRIVATE_KEY", "").strip()
        legacy_secret = os.getenv("MEDIAFLOW_LICENSE_SECRET", "").strip()

        return cls(
            env=env_val or "development",
            log_level=os.getenv("APP_LOG_LEVEL", "INFO").strip() or "INFO",
            download_dir=Path(os.getenv("MEDIAFLOW_DOWNLOAD_DIR", "").strip() or "downloads"),
            temp_dir=Path(os.getenv("MEDIAFLOW_TEMP_DIR", "").strip() or "downloads/.temp"),
            max_concurrent_downloads=max(1, min(int(os.getenv("MEDIAFLOW_MAX_CONCURRENT_DOWNLOADS", "").strip() or "3"), 20)),
            max_download_bytes=int(os.getenv("MEDIAFLOW_MAX_DOWNLOAD_BYTES", "").strip() or str(10 * 1024 * 1024 * 1024)),
            db_path=Path(os.getenv("MEDIAFLOW_DB_PATH", "").strip() or "mediaflow.db"),
            ffmpeg_path=os.getenv("FFMPEG_PATH", "").strip(),
            ffprobe_path=os.getenv("FFPROBE_PATH", "").strip(),
            license_public_key=pub_key or DEFAULT_DEV_PUBLIC_KEY,
            license_private_key=priv_key or DEFAULT_DEV_PRIVATE_KEY,
            license_secret=legacy_secret or "mediaflow_secret_key_v1_offline_auth",
        )


def get_config() -> AppConfig:
    """Return the active application configuration instance."""
    return AppConfig.from_env()
